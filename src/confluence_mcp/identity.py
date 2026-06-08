"""Per-request identity и разрешённые пространства.

Инструменты в server.py синхронные и используют глобальный клиент, поэтому личность
запроса передаётся через ContextVar, который заполняет Starlette-middleware на каждом
HTTP-запросе (см. server.py). Источник правды о правах — профили в config.py.
"""

from __future__ import annotations

from contextvars import ContextVar

from .config import WILDCARD_SPACE, get_config

# Имя профиля, выбранного для текущего запроса (None — ещё не установлено).
current_profile: ContextVar[str | None] = ContextVar("current_profile", default=None)

_config = get_config()


def resolve_profile(username: str | None, secret: str | None) -> str:
    """Выбрать имя профиля по заголовкам запроса.

    Профиль пользователя применяется только при совпадении app_secret. Иначе (нет/неверный
    секрет, неизвестный пользователь) — default_profile. Если app_secret в конфиге пуст,
    проверка секрета не выполняется (режим без сетевой защиты — см. план, часть C).
    """
    name = (username or "").strip()
    if not name:
        return _config.default_profile

    if _config.app_secret:
        if (secret or "") != _config.app_secret:
            return _config.default_profile

    if name in _config.profiles:
        return name
    return _config.default_profile


def get_allowed_spaces() -> list[str]:
    """Разрешённые space-ключи для текущего запроса (по профилю из ContextVar)."""
    profile = current_profile.get()
    if profile is None:
        profile = _config.default_profile
    return _config.profiles.get(profile, [])


def has_full_access(allowed: list[str] | None = None) -> bool:
    """True, если профиль видит все пространства (wildcard)."""
    spaces = allowed if allowed is not None else get_allowed_spaces()
    return WILDCARD_SPACE in spaces
