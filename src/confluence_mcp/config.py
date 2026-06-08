"""Configuration management for Confluence MCP server."""

import json
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

# Профиль с таким набором пространств видит всё (фильтр не накладывается).
WILDCARD_SPACE = "*"


@dataclass
class Config:
    """Configuration for Confluence connection."""
    base_url: str
    username: str
    api_token: str
    request_timeout: float = 30.0
    score_merge_max_variants: int = 12
    # --- Разграничение доступа (access profiles) ---
    app_secret: str = ""
    default_profile: str = "default"
    profiles: dict = field(default_factory=lambda: {"default": [WILDCARD_SPACE]})

    def allowed_spaces_for(self, username: str | None) -> list[str]:
        """Список разрешённых space-ключей для пользователя.

        Профиль выбирается по username; если username пуст/неизвестен — берётся
        default_profile. Возвращает [WILDCARD_SPACE] для полного доступа.
        """
        name = (username or "").strip()
        if name and name in self.profiles:
            return self.profiles[name]
        return self.profiles.get(self.default_profile, [WILDCARD_SPACE])


def get_config() -> Config:
    """Load configuration from environment variables.

    Returns:
        Config object with base_url, username and api_token

    Raises:
        ValueError: If required environment variables are not set
    """
    base_url = (os.getenv("CONFLUENCE_BASE_URL") or "").strip()
    username = (os.getenv("CONFLUENCE_USERNAME") or "").strip()
    api_token = (os.getenv("CONFLUENCE_API_TOKEN") or "").strip()

    if not base_url:
        raise ValueError(
            "CONFLUENCE_BASE_URL должен быть установлен в переменных окружения"
        )

    if not username:
        raise ValueError(
            "CONFLUENCE_USERNAME должен быть установлен в переменных окружения"
        )

    if not api_token:
        raise ValueError(
            "CONFLUENCE_API_TOKEN должен быть установлен в переменных окружения"
        )

    timeout_raw = os.getenv("CONFLUENCE_TIMEOUT", "30")
    try:
        request_timeout = max(5.0, float(timeout_raw))
    except ValueError:
        request_timeout = 30.0

    score_max_raw = os.getenv("SCORE_MERGE_MAX_VARIANTS", "12")
    try:
        score_merge_max_variants = max(4, min(int(score_max_raw), 24))
    except ValueError:
        score_merge_max_variants = 12

    app_secret, default_profile, profiles = _load_access_profiles()

    return Config(
        base_url=base_url.rstrip("/"),
        username=username,
        api_token=api_token,
        request_timeout=request_timeout,
        score_merge_max_variants=score_merge_max_variants,
        app_secret=app_secret,
        default_profile=default_profile,
        profiles=profiles,
    )


def _load_access_profiles() -> tuple[str, str, dict]:
    """Загрузить профили доступа из JSON (путь в ACCESS_PROFILES_PATH).

    Формат файла:
        {
          "app_secret": "...",
          "default_profile": "guest",
          "profiles": {"guest": {"spaces": ["KB1C"]}, "admin": {"spaces": ["*"]}}
        }

    Graceful fallback: если файл не задан/не найден/битый — возвращаем единственный
    профиль "default" с полным доступом, чтобы не сломать работу до настройки.
    Поведение и причина зафиксированы в плане proud-wandering-dream.md.
    """
    fallback = ("", "default", {"default": [WILDCARD_SPACE]})

    path = (os.getenv("ACCESS_PROFILES_PATH") or "").strip()
    if not path:
        path = "access_profiles.json"
    if not os.path.exists(path):
        return fallback

    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return fallback

    app_secret = str(data.get("app_secret") or "")
    default_profile = str(data.get("default_profile") or "default")

    profiles: dict[str, list[str]] = {}
    raw_profiles = data.get("profiles")
    if isinstance(raw_profiles, dict):
        for name, spec in raw_profiles.items():
            spaces = spec.get("spaces") if isinstance(spec, dict) else spec
            if isinstance(spaces, list):
                profiles[str(name)] = [str(s).strip() for s in spaces if str(s).strip()]

    if not profiles:
        return fallback
    if default_profile not in profiles:
        # default указывает на несуществующий профиль — самый безопасный выбор: пустой доступ.
        profiles.setdefault(default_profile, [])

    return app_secret, default_profile, profiles
