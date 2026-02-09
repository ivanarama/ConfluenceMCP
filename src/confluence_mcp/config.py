"""Configuration management for Confluence MCP server."""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Configuration for Confluence connection."""
    base_url: str
    pat_token: str


def get_config() -> Config:
    """Load configuration from environment variables.

    Returns:
        Config object with base_url and pat_token

    Raises:
        ValueError: If required environment variables are not set
    """
    base_url = os.getenv("CONFLUENCE_BASE_URL")
    pat_token = os.getenv("CONFLUENCE_PAT_TOKEN")

    if not base_url:
        raise ValueError(
            "CONFLUENCE_BASE_URL должен быть установлен в переменных окружения"
        )

    if not pat_token:
        raise ValueError(
            "CONFLUENCE_PAT_TOKEN должен быть установлен в переменных окружения"
        )

    return Config(base_url=base_url, pat_token=pat_token)
