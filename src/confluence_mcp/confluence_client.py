"""Confluence REST API client (Server/Data Center — /rest/api/)."""

from __future__ import annotations

from typing import Any

import requests
from requests.auth import HTTPBasicAuth


def _raise_for_status_with_body(response: requests.Response) -> None:
    """Like raise_for_status but include response body snippet for 4xx/5xx."""
    if response.ok:
        return
    snippet = (response.text or "").strip().replace("\n", " ")[:1200]
    if snippet:
        msg = f"{response.status_code} {response.reason} for {response.url}: {snippet}"
    else:
        msg = f"{response.status_code} {response.reason} for {response.url}"
    raise requests.HTTPError(msg, response=response)


class ConfluenceClient:
    """HTTP client for Confluence REST API."""

    def __init__(
        self,
        base_url: str,
        username: str,
        api_token: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.BASE_URL = base_url.rstrip("/")
        self.USERNAME = username
        self.API_TOKEN = api_token
        self._timeout = timeout
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(username, api_token)
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, url: str, *, params: dict[str, Any] | None = None) -> requests.Response:
        r = self.session.get(url, params=params, timeout=self._timeout)
        _raise_for_status_with_body(r)
        return r

    def search(self, cql: str, limit: int = 10, expand: list[str] | None = None) -> dict[str, Any]:
        limit_int = int(limit) if isinstance(limit, (int, str)) else 10
        q: dict[str, Any] = {"cql": cql, "limit": min(limit_int, 100)}
        if expand:
            q["expand"] = ",".join(expand)

        response = self._get(f"{self.BASE_URL}/rest/api/content/search", params=q)
        return response.json()

    def get_content(self, content_id: str, expand: list[str] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if expand:
            params["expand"] = ",".join(expand)

        response = self._get(
            f"{self.BASE_URL}/rest/api/content/{content_id}",
            params=params,
        )
        return response.json()

    def get_spaces(self, limit: int = 50) -> dict[str, Any]:
        limit_int = int(limit) if isinstance(limit, (int, str)) else 50
        response = self._get(
            f"{self.BASE_URL}/rest/api/space",
            params={"limit": limit_int},
        )
        return response.json()

    def get_current_user(self) -> dict[str, Any]:
        """Current user profile — cheap health check."""
        response = self._get(f"{self.BASE_URL}/rest/api/user/current")
        return response.json()
