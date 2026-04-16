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
) -> str:
    """Поиск страниц в Confluence (CQL).

    По умолчанию (multi_pass=true): из текста извлекаются pageId из ссылок; дополнительно выполняется
    несколько запросов по вариантам строки (полная фраза + токены с «_» и длинные слова), результаты
    объединяются без дубликатов. Для коротких вариантов используется title OR text, для длинных — text.
    multi_pass=false — одна классическая выборка text ~ «весь запрос» (старое поведение).
    Фильтр пространств: space_keys (список ключей) или один space_key; в space_key можно через запятую
    несколько ключей. Пусто — поиск по всем пространствам.
    content_type: page | blogpost | comment | attachment | space | all
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
    suffix = _cql_space_type_suffix(space_key, space_keys, ct)

    if not multi_pass:
        safe = escape_cql_string(q)
        cql = f'text ~ "{safe}"' + suffix
        result = client.search(cql=cql, limit=lim, expand=["space", "version"])
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

    id_suffix = _cql_type_only_suffix(ct)
    for pid in extract_page_ids_from_text(q):
        if len(merged) >= lim:
            break
        id_queries = [f"id = {pid}", f'id = "{escape_cql_string(pid)}"']
        for id_cql in id_queries:
            try:
                data = client.search(cql=id_cql + id_suffix, limit=1, expand=["space", "version"])
                take(data.get("results", []))
                break
            except Exception:
                continue

    for variant in search_query_variants(q, max_variants=24):
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

    payload = {"results": merged[:lim], "size": len(merged[:lim])}
    return json.dumps(payload, indent=2, ensure_ascii=False)


@mcp.tool()
def search_by_cql(cql: str, limit: int = 10, expand: list[str] | None = None) -> str:
    """Поиск сырой строкой CQL (для опытных пользователей). Ошибки Confluence вернутся в тексте исключения."""
    if expand is None:
        expand = ["space", "version"]
    cql_stripped = (cql or "").strip()
    if not cql_stripped:
        return json.dumps({"error": "cql не может быть пустым"}, ensure_ascii=False, indent=2)

    lim = max(1, min(int(limit), 100))
    result = client.search(cql=cql_stripped, limit=lim, expand=expand)
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
    result = client.get_children(content_id=pid, limit=lim)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def list_spaces(limit: int = 50) -> str:
    """Список пространств (spaces), до limit штук (макс. 100)."""
    lim = max(1, min(int(limit), 100))
    result = client.get_spaces(limit=lim)
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

    sse_app = mcp.http_app(transport="sse")
    streamable_http_app = mcp.http_app(transport="streamable-http", path="/mcp")

    app = Starlette(
        routes=[Route("/health", http_health)] + streamable_http_app.routes + sse_app.routes
    )

    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
