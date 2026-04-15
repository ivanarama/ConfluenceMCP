"""Расширение пользовательского запроса для поиска в Confluence (pageId в тексте, варианты токенов)."""

from __future__ import annotations

import re

_PAGE_ID_RE = re.compile(
    r"(?:[?&#]page[Ii]d=|page[Ii]d=)(\d+)|/content/(\d+)(?:/|$|\?|#)",
    re.IGNORECASE,
)


def extract_page_ids_from_text(text: str) -> list[str]:
    """Numeric content id из URL (viewpage.action?pageId=, REST /content/id)."""
    seen: dict[str, None] = {}
    for m in _PAGE_ID_RE.finditer(text or ""):
        pid = next(g for g in m.groups() if g)
        seen.setdefault(pid, None)
    return list(seen.keys())


def significant_words(
    text: str,
    *,
    min_len: int = 4,
    max_words: int = 14,
) -> list[str]:
    """
    Слова из запроса (латиница + кириллица) для отдельных CQL-проходов.
    min_len=4 чтобы «питы», «ручки» попадали в поиск; короче — много шума.
    """
    raw = re.findall(r"(?u)[\w-]+", text or "")
    seen_lower: set[str] = set()
    words: list[str] = []
    for w in raw:
        w = w.strip("-_")
        if len(w) < min_len:
            continue
        low = w.lower()
        if low in seen_lower:
            continue
        seen_lower.add(low)
        words.append(w)
    words.sort(key=len, reverse=True)
    return words[:max_words]


def search_query_variants(
    question: str,
    *,
    max_variants: int = 14,
    max_token_len: int = 240,
) -> list[str]:
    """
    Полная фраза + слова от 4 символов (рус/лат) + фрагменты с «_» (регламенты 1С и т.д.).
    """
    q = (question or "").strip()
    if not q:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        s = s.strip()
        if len(s) < 2 or s in seen:
            return
        if len(s) > max_token_len:
            s = s[:max_token_len]
        seen.add(s)
        out.append(s)

    add(q)
    parts = re.split(r"\s+", q)
    for p in sorted((x for x in parts if "_" in x and len(x) >= 6), key=len, reverse=True):
        add(p)
    for p in parts:
        p = re.sub(r"^[\s?!.,;:«»\"'()\[\]]+|[\s?!.,;:«»\"'()\[\]]+$", "", p)
        if len(p) >= 4:
            add(p)
    for w in significant_words(q, min_len=4, max_words=12):
        add(w)
    return out[:max_variants]
