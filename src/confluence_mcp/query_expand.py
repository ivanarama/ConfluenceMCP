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


def _split_camel(word: str) -> list[str]:
    """Split CamelCase (Latin or Cyrillic) into separate words.

    'ОбновлениеСообщенийВСервисе' → ['Обновление', 'Сообщений', 'В', 'Сервисе']
    'UpdateMessagesInService'      → ['Update', 'Messages', 'In', 'Service']
    """
    # Insert space: lowercase → UPPERCASE boundary (main camelCase split)
    s = re.sub(r'(?<=[а-яёa-z])(?=[А-ЯЁA-Z])', ' ', word)
    # Insert space: UPPERCASE sequence → Uppercase+lowercase (e.g. "HTMLParser" → "HTML Parser")
    s = re.sub(r'(?<=[А-ЯЁA-Z])(?=[А-ЯЁA-Z][а-яёa-z])', ' ', s)
    return [p for p in s.split() if len(p) >= 2]


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
    max_variants: int = 20,
    max_token_len: int = 240,
) -> list[str]:
    """
    Полная фраза + слова от 4 символов (рус/лат) + фрагменты с «_» + скользящие фразы 2-3 слова
    + CamelCase разбивка составных идентификаторов.

    Скользящие фразы позволяют найти страницы по частичному совпадению
    («Дата последнего регл. задания» → «Дата последнего», «последнего регл» и т.д.).
    CamelCase разбивка помогает с именами регламентов 1С/ERP
    («ОбновлениеСообщенийВСервисе» → «Обновление Сообщений Сервисе»).
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

    # 1. Полная фраза
    add(q)

    # 2. Фрагменты с «_» (имена регламентов, объектов 1С/ERP)
    parts = re.split(r"\s+", q)
    for p in sorted((x for x in parts if "_" in x and len(x) >= 6), key=len, reverse=True):
        add(p)

    # 3. Каждое слово отдельно (очищаем знаки препинания по краям)
    clean_parts: list[str] = []
    for p in parts:
        cp = re.sub(r"^[\s?!.,;:«»\"'()\[\]]+|[\s?!.,;:«»\"'()\[\]]+$", "", p)
        if len(cp) >= 3:
            clean_parts.append(cp)
        if len(cp) >= 4:
            add(cp)

    # 4. Скользящие фразы из 3 слов (ключевые для поиска по фрагменту текста)
    for i in range(len(clean_parts) - 2):
        phrase = " ".join(clean_parts[i:i + 3])
        if len(phrase) >= 8:
            add(phrase)

    # 5. Скользящие фразы из 2 слов
    for i in range(len(clean_parts) - 1):
        phrase = " ".join(clean_parts[i:i + 2])
        if len(phrase) >= 6:
            add(phrase)

    # 6. CamelCase разбивка составных слов (в т.ч. части с «_»)
    for p in parts:
        tokens = p.split("_")
        for tok in tokens:
            tok = tok.strip("-")
            if len(tok) < 4:
                continue
            camel_words = _split_camel(tok)
            if len(camel_words) > 1:
                # Фраза из разобранных частей
                add(" ".join(camel_words))
                # И каждое слово отдельно
                for cw in camel_words:
                    if len(cw) >= 4:
                        add(cw)

    # 7. Значимые слова по длине (финальное добивание, если лимит не исчерпан)
    for w in significant_words(q, min_len=4, max_words=12):
        add(w)

    return out[:max_variants]
