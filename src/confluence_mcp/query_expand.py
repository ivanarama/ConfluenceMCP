"""Расширение пользовательского запроса для поиска в Confluence (pageId в тексте, варианты токенов)."""

from __future__ import annotations

import re

from .noun_extract import has_pymorphy3, noun_phrase

# Слова, которые точно не встречаются в технической документации:
# вопросительные, указательные, дискурсные, личные местоимения.
# Намеренно НЕ включаем: регламент, задание, сообщение, выключить —
# эти слова могут быть в тексте страниц.
_RU_STOPWORDS: frozenset[str] = frozenset({
    # вопросительные слова
    "как", "где", "когда", "что", "кто", "зачем", "почему", "куда", "откуда", "чем", "чему",
    # указательные / относительные местоимения
    "это", "эта", "этот", "эти", "который", "которая", "которое", "которые",
    # модальные / дискурсные частицы
    "надо", "нужно", "можно", "нельзя",
    # личные местоимения
    "мне", "нам", "нас", "меня", "тебе", "вам", "вас",
})

# Синонимы и родственные формы для типичных корпоративных терминов.
# Ключ — нижний регистр; значение — список синонимов/родственных слов.
_SYNONYMS: dict[str, list[str]] = {
    "директор":     ["руководитель", "начальник", "директорат", "дирекция"],
    "руководитель": ["директор", "начальник", "директорат", "дирекция"],
    "клиент":       ["заказчик", "абонент", "покупатель"],
    "оформить":     ["принять", "создать", "оформление", "зарегистрировать"],
    "принять":      ["оформить", "создать", "прием", "приема"],
    "заявка":       ["обращение", "заказ", "запрос"],
    "позвонить":    ["звонок", "вызов", "телефонный"],
    "звонок":       ["вызов", "позвонить", "телефонный"],
}

# Аббревиатуры, типичные для 1С/ERP-документации.
# Ключ — сокращение в нижнем регистре; значение — варианты полного написания.
_1C_ABBREV: dict[str, list[str]] = {
    "регл":  ["регламент", "регламентное", "регламентного"],
    "рег":   ["регламент", "регламентное"],
    "зад":   ["задание", "задания"],
    "обр":   ["обработка", "обработки"],
    "справ": ["справочник", "справочника"],
    "докум": ["документ", "документа"],
}

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


def _is_stopword(token: str) -> bool:
    """Возвращает True для слов, которые точно не встречаются в технической документации."""
    return token.lower() in _RU_STOPWORDS


# Короткие русские слова, которые не являются аббревиатурами,
# даже если написаны в верхнем регистре (в запросах ВСЕГДА CAPS).
_NOT_ABBREV: frozenset[str] = frozenset({
    "до", "на", "в", "к", "с", "по", "из", "за", "и", "о", "у",
    "но", "а", "не", "то", "со", "ко", "бы", "ли", "же", "уж",
})

_RU_VOWELS = frozenset("аеёиоуыэюя")


def _is_abbrev(token: str) -> bool:
    """Аббревиатуры: ХД, МСК, РФ, НДС, IT, HR, API.
    Не предлоги (ДО, НА) и не обычные слова (ЧАСА, МОЖНО)."""
    if len(token) < 2 or token.upper() != token or not token.isalpha():
        return False
    if token.lower() in _NOT_ABBREV:
        return False
    if token.isascii():
        return True
    # Русские аббревиатуры состоят только из согласных: ХД, МСК, КВ, РФ
    return not any(c.lower() in _RU_VOWELS for c in token)


def expand_abbrev(token: str) -> list[str]:
    """Возвращает полные формы для известных 1С-аббревиатур (+ сам токен).

    'регл' → ['регл', 'регламент', 'регламентное', 'регламентного']
    Неизвестные токены → [token].
    """
    key = token.lower().rstrip(".")
    expansions = _1C_ABBREV.get(key)
    if not expansions:
        return [token]
    return [token] + expansions


def search_query_variants(
    question: str,
    *,
    max_variants: int = 20,
    max_token_len: int = 240,
) -> list[str]:
    """
    Порядок от конкретного к общему:
      1. Полная фраза
      2. Идентификаторы с «_» (точное имя регламента/объекта 1С)
      3. CamelCase-токены целиком («ОбновлениеСообщенийВСервисе»)
      4. CamelCase многословные фразы («Обновление Сообщений Сервисе»)
      5. Скользящие фразы из 3 слов  ← многословные = конкретные
      6. Скользящие фразы из 2 слов
      7. Одиночные слова запроса (не стоп-слова, не даты)
      8. CamelCase отдельные слова («Обновление», «Сообщений» …)
      9. significant_words — добивка

    Одиночные слова (шаги 7-8) намеренно идут ПОСЛЕ фраз: «Дата» или «последнего»
    в одиночку возвращают десятки нерелевантных страниц и заполняют limit раньше,
    чем фраза «Дата последнего регл» находит нужную.

    Расширение аббревиатур (регл→регламентного) убрано: Confluence индексирует
    «регл.» именно как «регл», и поиск «регламентного» даёт ложные хиты.
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

    # 1b. Noun-only phrase (высокий приоритет, если pymorphy3 доступен)
    if has_pymorphy3():
        np = noun_phrase(q)
        if np and np != q:
            add(np)

    # 1c. Аббревиатуры из запроса: отдельные + пары (ХД МСК, IT HR)
    #     Высокий приоритет — короткие, но очень точные маркеры.
    abbrevs = [p for p in re.split(r"\s+", q) if _is_abbrev(p)]
    for a in abbrevs:
        add(a)
    if len(abbrevs) >= 2:
        for i in range(len(abbrevs)):
            for j in range(i + 1, len(abbrevs)):
                add(f"{abbrevs[i]} {abbrevs[j]}")

    # 1d. Синонимы: заменяем слова из запроса на известные синонимы
    parts = re.split(r"\s+", q)
    for part in parts:
        syns = _SYNONYMS.get(part.lower())
        if syns:
            for syn in syns:
                # Синоним целиком
                add(syn)
                # Замена слова в полной фразе
                replaced = q.replace(part, syn)
                if replaced != q:
                    add(replaced)

    parts = re.split(r"\s+", q)
    underscore_parts = sorted(
        (x for x in parts if "_" in x and len(x) >= 6), key=len, reverse=True
    )

    # 2. Идентификаторы с «_» целиком
    for p in underscore_parts:
        add(p)

    # 3. CamelCase-токены целиком (без разбивки): «ОбновлениеСообщенийВСервисе»
    for p in underscore_parts:
        for tok in p.split("_"):
            tok = tok.strip("-")
            if len(tok) >= 4:
                add(tok)

    # 4. CamelCase многословные фразы: «Обновление Сообщений Сервисе»
    for p in underscore_parts:
        for tok in p.split("_"):
            tok = tok.strip("-")
            if len(tok) < 4:
                continue
            camel_words = _split_camel(tok)
            if len(camel_words) > 1:
                add(" ".join(camel_words))

    # Собираем clean_parts для фраз (без стоп-слов и дат)
    clean_parts: list[str] = []
    for p in parts:
        cp = re.sub(r"^[\s?!.,;:«»\"'()\[\]]+|[\s?!.,;:«»\"'()\[\]]+$", "", p)
        if (len(cp) >= 3 or _is_abbrev(cp)) and not _is_stopword(cp) and not _is_date_like(cp):
            clean_parts.append(cp)

    meaningful = [w for w in clean_parts if not _is_date_like(w) and not w.isdigit()]

    # 5. Скользящие фразы из 3 слов — конкретнее одиночных слов, идут первыми
    for i in range(len(meaningful) - 2):
        phrase = " ".join(meaningful[i:i + 3])
        if len(phrase) >= 8:
            add(phrase)

    # 6. Скользящие фразы из 2 слов
    for i in range(len(meaningful) - 1):
        phrase = " ".join(meaningful[i:i + 2])
        if len(phrase) >= 6:
            add(phrase)

    # 7. Одиночные слова запроса (идут ПОСЛЕ фраз)
    # Аббревиатуры (ХД, МСК, IT) проходят при len >= 2, остальные — len >= 4
    for cp in clean_parts:
        if len(cp) >= 4 or _is_abbrev(cp):
            add(cp)

    # 8. CamelCase отдельные слова — самые общие
    for p in underscore_parts:
        for tok in p.split("_"):
            tok = tok.strip("-")
            if len(tok) < 4:
                continue
            for cw in _split_camel(tok):
                if len(cw) >= 4:
                    add(cw)
    for p in parts:
        if "_" in p:
            continue
        tok = re.sub(r"^[\s?!.,;:«»\"'()\[\]]+|[\s?!.,;:«»\"'()\[\]]+$", "", p).strip("-")
        if len(tok) < 4:
            continue
        camel_words = _split_camel(tok)
        if len(camel_words) > 1:
            add(" ".join(camel_words))
            for cw in camel_words:
                if len(cw) >= 4:
                    add(cw)

    # 9. Значимые слова по длине (финальное добивание)
    for w in significant_words(q, min_len=4, max_words=12):
        add(w)

    return out[:max_variants]
