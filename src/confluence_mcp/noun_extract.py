"""Extract nouns from Russian text using pymorphy3 (optional dependency)."""

from __future__ import annotations

import re

_HAS_MORPH = False
_MorphAnalyzer = None

try:
    import pymorphy3

    _MorphAnalyzer = pymorphy3.MorphAnalyzer
    _HAS_MORPH = True
except ImportError:
    pass


def has_pymorphy3() -> bool:
    """Check if pymorphy3 is available."""
    return _HAS_MORPH


def extract_nouns(text: str, *, min_len: int = 3) -> list[str]:
    """Extract noun words from Russian text.

    Returns unique nouns in order of appearance.
    Returns empty list if pymorphy3 is not installed.
    """
    if not _HAS_MORPH or not text:
        return []

    morph = _MorphAnalyzer()
    words = re.findall(r"(?u)[а-яёА-ЯЁa-zA-Z]+", text)
    nouns: list[str] = []
    seen: set[str] = set()

    for word in words:
        if len(word) < min_len:
            continue
        low = word.lower()
        if low in seen:
            continue
        parsed = morph.parse(word)
        if parsed and "NOUN" in parsed[0].tag:
            seen.add(low)
            nouns.append(word)

    return nouns


def noun_phrase(text: str) -> str | None:
    """Extract a space-joined noun phrase from text.

    Returns None if fewer than 1 noun found (not useful as a variant).
    """
    nouns = extract_nouns(text)
    if not nouns:
        return None
    return " ".join(nouns)
