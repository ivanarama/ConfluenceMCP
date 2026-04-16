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


_DATE_LIKE_RE = re.compile(r"^\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}$")


def _is_date_like(token: str) -> bool:
    """Возвращает True для дат вида 13.01.2026 — плохих поисковых токенов."""
    return bool(_DATE_LIKE_RE.match(token))


def search_query_variants(
    question: str,
    *,
    max_variants: int = 20,
    max_token_len: int = 240,
) -> list[str]:
    """
    Полная фраза + CamelCase разбивка идентификаторов с «_» (высокий приоритет)
    + слова от 4 символов + скользящие фразы 2-3 слова.

    Порядок приоритетов намеренный: CamelCase-части имён регламентов 1С/ERP
    («ОбновлениеСообщенийВСервисе» → «Обновление», «Сообщений», «Сервисе»)
    дают самый точный результат и поэтому идут ДО скользящих фраз.
    Скользящие фразы полезны для поиска по обычному тексту, но занимают много слотов.
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

    # 2. Фрагменты с «_» (имена регламентов, объектов 1С/ERP) + их CamelCase-разбивка
    parts = re.split(r"\s+", q)
    for p in sorted((x for x in parts if "_" in x and len(x) >= 6), key=len, reverse=True):
        add(p)
        # CamelCase каждого токена внутри идентификатора с «_» — высокий приоритет
        for tok in p.split("_"):
            tok = tok.strip("-")
            if len(tok) < 4:
                continue
            # Сам токен целиком (например «ОбновлениеСообщенийВСервисе»)
            add(tok)
            camel_words = _split_camel(tok)
            if len(camel_words) > 1:
                add(" ".join(camel_words))
                for cw in camel_words:
                    if len(cw) >= 4:
                        add(cw)

    # 3. Каждое слово отдельно (очищаем знаки препинания по краям; даты пропускаем)
    clean_parts: list[str] = []
    for p in parts:
        cp = re.sub(r"^[\s?!.,;:«»\"'()\[\]]+|[\s?!.,;:«»\"'()\[\]]+$", "", p)
        if len(cp) >= 3:
            clean_parts.append(cp)
        if len(cp) >= 4 and not _is_date_like(cp):
            add(cp)

    # 4. Скользящие фразы из 3 слов (только нечисловые токены)
    meaningful = [w for w in clean_parts if not _is_date_like(w) and not w.isdigit()]
    for i in range(len(meaningful) - 2):
        phrase = " ".join(meaningful[i:i + 3])
        if len(phrase) >= 8:
            add(phrase)

    # 5. Скользящие фразы из 2 слов
    for i in range(len(meaningful) - 1):
        phrase = " ".join(meaningful[i:i + 2])
        if len(phrase) >= 6:
            add(phrase)

    # 6. CamelCase разбивка обычных слов (без «_»)
    for p in parts:
        if "_" in p:
            continue  # уже обработано в шаге 2
        tok = re.sub(r"^[\s?!.,;:«»\"'()\[\]]+|[\s?!.,;:«»\"'()\[\]]+$", "", p).strip("-")
        if len(tok) < 4:
            continue
        camel_words = _split_camel(tok)
        if len(camel_words) > 1:
            add(" ".join(camel_words))
            for cw in camel_words:
                if len(cw) >= 4:
                    add(cw)

    # 7. Значимые слова по длине (финальное добивание, если лимит не исчерпан)
    for w in significant_words(q, min_len=4, max_words=12):
        add(w)

    return out[:max_variants]
