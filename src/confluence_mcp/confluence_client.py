"""Confluence REST API client."""

from __future__ import annotations

import requests
from requests.auth import HTTPBasicAuth
from typing import Any


class ConfluenceClient:
    """Client for interacting with Confluence REST API v2."""

    BASE_URL: str
    USERNAME: str
    API_TOKEN: str

    def __init__(self, base_url: str, username: str, api_token: str) -> None:
        """Initialize the Confluence client.

        Args:
            base_url: Base URL of Confluence instance (e.g., https://domain.atlassian.net/wiki)
            username: Email address for authentication
            api_token: API token for authentication
        """
        self.BASE_URL = base_url.rstrip("/")
        self.USERNAME = username
        self.API_TOKEN = api_token
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(username, api_token)
        self.session.headers.update({
            "Accept": "application/json"
        })

    def search(self, cql: str, limit: int = 10, expand: list[str] | None = None) -> dict[str, Any]:
        """Execute search with CQL query.

        Args:
            cql: CQL query string
            limit: Maximum number of results (max 100)
            expand: List of fields to expand (space, version, container, etc.)

        Returns:
            Dictionary with search results

        Raises:
            requests.HTTPError: If the request fails
        """
        params: dict[str, Any] = {"cql": cql, "limit": min(limit, 100)}
        if expand:
            params["expand"] = ",".join(expand)

        response = self.session.get(
            f"{self.BASE_URL}/rest/api/content/search",
            params=params
        )
        response.raise_for_status()
        return response.json()

    def get_content(self, content_id: str, expand: list[str] | None = None) -> dict[str, Any]:
        """Get content by ID.

        Args:
            content_id: ID of the content
            expand: List of fields to expand (space, version, body.view, etc.)

        Returns:
            Dictionary with content data

        Raises:
            requests.HTTPError: If the request fails
        """
        params: dict[str, Any] = {}
        if expand:
            params["expand"] = ",".join(expand)

        response = self.session.get(
            f"{self.BASE_URL}/rest/api/content/{content_id}",
            params=params
        )
        response.raise_for_status()
        return response.json()

    def get_spaces(self, limit: int = 50) -> dict[str, Any]:
        """Get list of available spaces.

        Args:
            limit: Maximum number of spaces to return

        Returns:
            Dictionary with spaces data

        Raises:
            requests.HTTPError: If the request fails
        """
        response = self.session.get(
            f"{self.BASE_URL}/rest/api/space",
            params={"limit": limit}
        )
        response.raise_for_status()
        return response.json()
