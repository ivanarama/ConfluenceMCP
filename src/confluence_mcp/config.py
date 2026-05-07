"""Configuration management for Confluence MCP server."""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Configuration for Confluence connection."""
    base_url: str
    username: str
    api_token: str
    request_timeout: float = 30.0
    score_merge_max_variants: int = 12


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

    return Config(
        base_url=base_url.rstrip("/"),
        username=username,
        api_token=api_token,
        request_timeout=request_timeout,
        score_merge_max_variants=score_merge_max_variants,
    )
