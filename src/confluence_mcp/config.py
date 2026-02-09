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


def get_config() -> Config:
    """Load configuration from environment variables.

    Returns:
        Config object with base_url, username and api_token

    Raises:
        ValueError: If required environment variables are not set
    """
    base_url = os.getenv("CONFLUENCE_BASE_URL")
    username = os.getenv("CONFLUENCE_USERNAME")
    api_token = os.getenv("CONFLUENCE_API_TOKEN")

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

    return Config(base_url=base_url, username=username, api_token=api_token)
