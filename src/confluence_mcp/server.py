"""MCP Server for Confluence — SSE and streamable-http transports."""

from __future__ import annotations

import datetime
import json
import os
import subprocess
from typing import Any

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .confluence_client import ConfluenceClient
from .config import get_config
from .cql_escape import escape_cql_string
from .identity import current_profile, get_allowed_spaces, has_full_access, resolve_profile
from .query_expand import extract_page_ids_from_text, search_query_variants

config = get_config()
client = ConfluenceClient(
    config.base_url,
    config.username,
    config.api_token,
    timeout=config.request_timeout,
)

SERVER_NAME = "confluence-search"
SERVER_HOST = os.getenv("MCP_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("MCP_PORT", "8003"))

_CQL_CONTENT_TYPES = frozenset({"page", "blogpost", "comment", "attachment", "space", "all"})

mcp = FastMCP(SERVER_NAME)


def _normalize_space_keys(space_key: str | None, space_keys: list[str] | None) -> list[str]:
    keys: list[str] = []
    if space_keys:
        keys = [str(k).strip() for k in space_keys if str(k).strip()]
    if not keys and space_key and space_key.strip():
        keys = [k.strip() for k in space_key.split(",") if k.strip()]
    return keys


def _cql_space_type_suffix(
    space_key: str | None,
    space_keys: list[str] | None,
    content_type: str,
) -> str:
    parts: list[str] = []
    keys = _normalize_space_keys(space_key, space_keys)
    if len(keys) == 1:
        parts.append(f'space = "{escape_cql_string(keys[0])}"')
    elif len(keys) > 1:
        inner = " OR ".join(f'space = "{escape_cql_string(k)}"' for k in keys)
        parts.append(f"({inner})")
    if content_type != "all":
        parts.append(f'type = "{content_type}"')
    if not parts:
        return ""
    return " AND " + " AND ".join(parts)


_DENIED_MARKER = object()


def _resolve_space_filter(
    space_key: str | None,
    space_keys: list[str] | None,
) -> tuple[list[str] | None, bool]:
    """Свести запрошенные пользователем пространства к разрешённым профилем.

    Возвращает (effective, denied):
      effective — список ключей для фильтра CQL, либо None (без ограничения по space);
      denied    — True, если пользователь запросил только запрещённые пространства
                  (нужно вернуть пустой результат, ничего не показывая).
    Клиентскому списку не доверяем: он может только сузить доступ в пределах разрешённого.
    """
    requested = _normalize_space_keys(space_key, space_keys)
    allowed = get_allowed_spaces()

    if has_full_access(allowed):
        return (requested or None), False

    if not allowed:
        return [], True

    if requested:
        effective = [k for k in requested if k in allowed]
        return effective, len(effective) == 0
    return list(allowed), False


def _cql_space_keys_clause(keys: list[str]) -> str:
    """`space in ("A","B")` для непустого списка ключей."""
    inner = ", ".join(f'"{escape_cql_string(k)}"' for k in keys)
    return f"space in ({inner})"


def _apply_cql_access(cql: str) -> tuple[str | None, bool]:
    """Ограничить сырой CQL разрешёнными профилю пространствами.

    Возвращает (cql, denied): при denied=True доступа к пространствам нет — вернуть пусто.
    Для wildcard CQL не меняется.
    """
    allowed = get_allowed_spaces()
    if has_full_access(allowed):
        return cql, False
    if not allowed:
        return None, True
    return f"({cql}) AND {_cql_space_keys_clause(allowed)}", False


def _space_allowed(space_key: str | None) -> bool:
    """True, если пространство доступно текущему профилю."""
    allowed = get_allowed_spaces()
    if has_full_access(allowed):
        return True
    return bool(space_key) and space_key in set(allowed)


def _denied_space_response() -> str:
    return json.dumps(
        {"error": "Доступ к пространству запрещён"},
        ensure_ascii=False,
        indent=2,
    )


def _filter_results_by_space(results: list[Any]) -> list[Any]:
    """Оставить только результаты из разрешённых профилю пространств.

    Защита «в глубину»: подстраховывает CQL-фильтр и закрывает поиск по id из ссылок
    (он намеренно не режется по space, чтобы найти страницу, см. _cql_type_only_suffix).
    """
    allowed = get_allowed_spaces()
    if has_full_access(allowed):
        return results
    allowed_set = set(allowed)
    out: list[Any] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        space_key = (r.get("space") or {}).get("key")
        if space_key in allowed_set:
            out.append(r)
    return out


def _cql_type_only_suffix(content_type: str) -> str:
    """Только type — для поиска по id из ссылки (не режем по space, иначе страница «в другом space» пропадает)."""
    if (content_type or "page").strip().lower() == "all":
        return ""
    ct = (content_type or "page").strip().lower()
    return f' AND type = "{ct}"'


def _cql_clause_for_variant(variant: str) -> str:
    """Короткие запросы ищем и в title — заголовки часто совпадают с именами регламентов / метаданными."""
    safe = escape_cql_string(variant)
    if len(variant) <= 120:
        return f'(title ~ "{safe}" OR text ~ "{safe}")'
    return f'text ~ "{safe}"'


@mcp.tool()
def search_content(
    query: str,
    space_key: str | None = None,
    space_keys: list[str] | None = None,
    content_type: str = "page",
    limit: int = 10,
    multi_pass: bool = True,
    score_merge: bool = True,
    score_merge_max_variants: int = 0,
    llm_rewrite: bool = True,
) -> str:
    """Поиск страниц в Confluence (CQL).

    По умолчанию (multi_pass=true): из текста извлекаются pageId из ссылок; дополнительно выполняется
    несколько запросов по вариантам строки (полная фраза + токены с «_» и длинные слова), результаты
    объединяются без дубликатов. Для коротких вариантов используется title OR text, для длинных — text.
    multi_pass=false — одна классическая выборка text ~ «весь запрос» (старое поведение).
    Фильтр пространств: space_keys (список ключей) или один space_key; в space_key можно через запятую
    несколько ключей. Пусто — поиск по всем пространствам.
    content_type: page | blogpost | comment | attachment | space | all
    score_merge: true — запустить все варианты, ранжировать по числу совпавших (score-based merging).
    score_merge_max_variants: макс. число вариантов для score_merge (0 = из конфига, по умолч. 12).
    llm_rewrite: true — переформулировать запрос через LLM перед поиском (требует LLM_REWRITE_ENDPOINT).
    """
    q = (query or "").strip()
    if not q:
        return json.dumps(
            {"error": "query не может быть пустым", "results": []},
            ensure_ascii=False,
            indent=2,
        )

    ct = (content_type or "page").strip().lower()
    if ct not in _CQL_CONTENT_TYPES:
        return json.dumps(
            {
                "error": f"content_type должен быть одним из: {sorted(_CQL_CONTENT_TYPES)}",
                "got": content_type,
            },
            ensure_ascii=False,
            indent=2,
        )

    lim = max(1, min(int(limit), 100))
    effective_spaces, denied = _resolve_space_filter(space_key, space_keys)
    if denied:
        return json.dumps(
            {"results": [], "size": 0, "variants": 0, "llm": False},
            ensure_ascii=False,
            indent=2,
        )
    suffix = _cql_space_type_suffix(None, effective_spaces, ct)

    if not multi_pass:
        safe = escape_cql_string(q)
        cql = f'text ~ "{safe}"' + suffix
        result = client.search(cql=cql, limit=lim, expand=["space", "version"])
        result["results"] = _filter_results_by_space(result.get("results", []))
        return json.dumps(result, indent=2, ensure_ascii=False)

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    def take(items: list[Any]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            iid = str(item.get("id", ""))
            if not iid or iid in seen:
                continue
            seen.add(iid)
            merged.append(item)

    # --- LLM rewrite: generate alternative phrasings ---
    llm_variants: list[str] = []
    llm_used = False
    if llm_rewrite and multi_pass:
        from .llm_rewrite import is_llm_rewrite_enabled, rewrite_query

        if is_llm_rewrite_enabled():
            llm_variants = rewrite_query(q)
            llm_used = len(llm_variants) > 0

    # --- Page-ID lookups (same for both modes) ---
    id_suffix = _cql_type_only_suffix(ct)
    id_hits: list[dict[str, Any]] = []
    for pid in extract_page_ids_from_text(q):
        if not score_merge and len(merged) >= lim:
            break
        id_queries = [f"id = {pid}", f'id = "{escape_cql_string(pid)}"']
        for id_cql in id_queries:
            try:
                data = client.search(cql=id_cql + id_suffix, limit=1, expand=["space", "version"])
                results = data.get("results", [])
                if score_merge:
                    id_hits.extend(results)
                else:
                    take(results)
                break
            except Exception:
                continue

    # --- Build variant list ---
    max_var = score_merge_max_variants if score_merge_max_variants > 0 else config.score_merge_max_variants
    all_variants = llm_variants + search_query_variants(q, max_variants=max_var if score_merge else 24)

    # --- Score-based merging ---
    if score_merge:
        from .scoring import score_results, variant_weight

        all_variant_hits: list[list[dict[str, Any]]] = []
        variant_weights: list[float] = []

        if id_hits:
            all_variant_hits.append(id_hits)
            variant_weights.append(3.0)

        for variant in all_variants:
            clause = _cql_clause_for_variant(variant)
            full_cql = clause + suffix
            try:
                data = client.search(cql=full_cql, limit=min(lim + 5, 50), expand=["space", "version"])
                hits = data.get("results", [])
                all_variant_hits.append(hits)
                variant_weights.append(variant_weight(variant, q))
            except Exception:
                continue

        scored = score_results(all_variant_hits, weights=variant_weights, limit=lim)
        merged = [s.item for s in scored]
    else:
        # --- Original first-come-first-serve logic ---
        for variant in all_variants:
            if len(merged) >= lim:
                break
            clause = _cql_clause_for_variant(variant)
            full_cql = clause + suffix
            need = lim - len(merged)
            fetch = min(max(need + 3, 5), 50)
            try:
                data = client.search(cql=full_cql, limit=fetch, expand=["space", "version"])
                take(data.get("results", []))
            except Exception:
                continue

    merged = _filter_results_by_space(merged)

    payload: dict[str, Any] = {
        "results": merged[:lim],
        "size": len(merged[:lim]),
        "variants": len(all_variants),
        "llm": llm_used,
    }
    if llm_used:
        payload["llm_variants"] = llm_variants
    return json.dumps(payload, indent=2, ensure_ascii=False)


@mcp.tool()
def search_by_cql(cql: str, limit: int = 10, expand: list[str] | None = None) -> str:
    """Поиск сырой строкой CQL (для опытных пользователей). Ошибки Confluence вернутся в тексте исключения."""
    if expand is None:
        expand = ["space", "version"]
    elif "space" not in expand:
        # space нужен для пост-фильтрации по разрешённым пространствам
        expand = [*expand, "space"]
    cql_stripped = (cql or "").strip()
    if not cql_stripped:
        return json.dumps({"error": "cql не может быть пустым"}, ensure_ascii=False, indent=2)

    # Принудительное ограничение по разрешённым пространствам: сырой CQL оборачиваем.
    cql_stripped, denied = _apply_cql_access(cql_stripped)
    if denied:
        return json.dumps({"results": [], "size": 0}, ensure_ascii=False, indent=2)

    lim = max(1, min(int(limit), 100))
    result = client.search(cql=cql_stripped, limit=lim, expand=expand)
    result["results"] = _filter_results_by_space(result.get("results", []))
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def get_page_content(page_id: str) -> str:
    """Полное содержимое страницы по ID.

    Возвращает: body.view (HTML), space, version, ancestors (цепочка родителей),
    children.page (список дочерних страниц с id и title).
    Используй ancestors и children.page чтобы понять, где искать связанную информацию,
    если на текущей странице ответа нет.
    """
    pid = (page_id or "").strip()
    if not pid:
        return json.dumps({"error": "page_id не может быть пустым"}, ensure_ascii=False, indent=2)

    result = client.get_content(
        content_id=pid,
        expand=["space", "version", "body.view", "ancestors", "children.page"],
    )
    if not _space_allowed((result.get("space") or {}).get("key")):
        return _denied_space_response()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def get_page_children(page_id: str, limit: int = 25) -> str:
    """Список дочерних страниц (id, title, version) для заданного page_id.

    Полезно когда страница является разделом/оглавлением: ответ на конкретный вопрос
    часто находится на одной из дочерних страниц.
    limit: максимум страниц (по умолчанию 25, не более 100).
    """
    pid = (page_id or "").strip()
    if not pid:
        return json.dumps({"error": "page_id не может быть пустым"}, ensure_ascii=False, indent=2)

    lim = max(1, min(int(limit), 100))
    # Сначала проверяем пространство родителя, чтобы не раскрывать дочерние из чужого space.
    if not has_full_access():
        parent = client.get_content(content_id=pid, expand=["space"])
        if not _space_allowed((parent.get("space") or {}).get("key")):
            return _denied_space_response()
    result = client.get_children(content_id=pid, limit=lim)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def list_spaces(limit: int = 50) -> str:
    """Список пространств (spaces), до limit штук (макс. 100)."""
    lim = max(1, min(int(limit), 100))
    result = client.get_spaces(limit=lim)
    if not has_full_access():
        allowed_set = set(get_allowed_spaces())
        spaces = result.get("results", [])
        result["results"] = [s for s in spaces if isinstance(s, dict) and s.get("key") in allowed_set]
        result["size"] = len(result["results"])
    return json.dumps(result, indent=2, ensure_ascii=False)


def _git_commit() -> str:
    """Возвращает короткий git-хэш: сначала из ENV (вшитой при docker build), затем через git."""
    env_val = os.getenv("GIT_COMMIT", "").strip()
    if env_val and env_val != "unknown":
        return env_val
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(__file__),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


@mcp.tool()
def confluence_health() -> str:
    """Проверка доступности Confluence, учётных данных и версии сервера.

    Поле git_commit показывает хэш коммита, из которого собран контейнер.
    Используй его чтобы убедиться, что запущена нужная версия кода.
    """
    git = _git_commit()
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        u: dict[str, Any] = client.get_current_user()
        payload = {
            "ok": True,
            "username": u.get("username"),
            "userKey": u.get("userKey"),
            "displayName": u.get("displayName"),
            "type": u.get("type"),
            "git_commit": git,
            "checked_at": started_at,
        }
    except Exception as exc:  # noqa: BLE001 — отдаём ошибку клиенту MCP как JSON
        payload = {"ok": False, "error": str(exc), "git_commit": git, "checked_at": started_at}
    return json.dumps(payload, indent=2, ensure_ascii=False)


class IdentityMiddleware:
    """ASGI-middleware: по заголовкам X-Localchat-User / X-Localchat-Secret выбирает
    профиль доступа и кладёт его имя в ContextVar для текущего запроса.

    Чистый ASGI (не BaseHTTPMiddleware), чтобы ContextVar, установленный перед вызовом
    приложения, был виден синхронным инструментам в той же задаче.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        profile = resolve_profile(
            headers.get("x-localchat-user"),
            headers.get("x-localchat-secret"),
        )
        token = current_profile.set(profile)
        try:
            await self.app(scope, receive, send)
        finally:
            current_profile.reset(token)


async def http_health(request: Request) -> JSONResponse:
    """GET /health — версия сервера и доступность Confluence. Открывается в браузере."""
    git = _git_commit()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        u = client.get_current_user()
        body = {
            "ok": True,
            "git_commit": git,
            "checked_at": now,
            "confluence_user": u.get("displayName") or u.get("username"),
            "confluence_url": config.base_url,
        }
        status = 200
    except Exception as exc:  # noqa: BLE001
        body = {"ok": False, "git_commit": git, "checked_at": now, "error": str(exc)}
        status = 503
    return JSONResponse(body, status_code=status)


if __name__ == "__main__":
    import uvicorn
    from contextlib import AsyncExitStack, asynccontextmanager

    sse_app = mcp.http_app(transport="sse")
    streamable_http_app = mcp.http_app(transport="streamable-http", path="/mcp")

    @asynccontextmanager
    async def combined_lifespan(app):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(sse_app.lifespan(app))
            await stack.enter_async_context(streamable_http_app.lifespan(app))
            yield

    from starlette.middleware import Middleware

    app = Starlette(
        routes=[Route("/health", http_health)] + streamable_http_app.routes + sse_app.routes,
        middleware=[Middleware(IdentityMiddleware)],
        lifespan=combined_lifespan,
    )

    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
