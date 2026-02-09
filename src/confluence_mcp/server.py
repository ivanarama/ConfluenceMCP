"""MCP Server for Confluence search with StreamableHttp/SSE transport."""

from __future__ import annotations

import json
import os
from fastmcp import FastMCP

from .confluence_client import ConfluenceClient
from .config import get_config

mcp = FastMCP("confluence-search")

config = get_config()
client = ConfluenceClient(config.base_url, config.username, config.api_token)


@mcp.tool
def search_content(
    query: str,
    space_key: str | None = None,
    content_type: str = "page",
    limit: int = 10
) -> str:
    """Search content in Confluence by keywords.

    Args:
        query: Keywords to search for
        space_key: Space key filter (optional)
        content_type: Content type - page, blogpost, or all (default: page)
        limit: Maximum number of results (default: 10, max: 100)

    Returns:
        JSON string with search results
    """
    # Build CQL query from parameters
    cql_parts = [f'text ~ "{query}"']

    if space_key:
        cql_parts.append(f'space = "{space_key}"')

    if content_type and content_type != "all":
        cql_parts.append(f'type = "{content_type}"')

    cql = " AND ".join(cql_parts)

    # Always expand useful fields
    expand = ["space", "version"]

    try:
        result = client.search(cql=cql, limit=limit, expand=expand)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


@mcp.tool
def search_by_cql(
    cql: str,
    limit: int = 10,
    expand: list[str] | None = None
) -> str:
    """Advanced search using CQL (Confluence Query Language).

    Args:
        cql: CQL query (e.g., 'space = "DEV" AND type = "page" AND created > "2024-01-01"')
        limit: Maximum number of results
        expand: List of fields to expand (space, version, container, etc.)

    Returns:
        JSON string with search results
    """
    if expand is None:
        expand = ["space", "version"]

    try:
        result = client.search(cql=cql, limit=limit, expand=expand)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


@mcp.tool
def get_page_content(page_id: str) -> str:
    """Get full content of a page by ID.

    Args:
        page_id: Confluence page ID

    Returns:
        Page content in View format
    """
    expand = ["space", "version", "body.view"]
    try:
        result = client.get_content(content_id=page_id, expand=expand)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


@mcp.tool
def list_spaces(limit: int = 50) -> str:
    """Get list of available spaces.

    Args:
        limit: Maximum number of spaces

    Returns:
        JSON string with list of spaces
    """
    try:
        result = client.get_spaces(limit=limit)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


# Entry point for running the server
if __name__ == "__main__":
    # Get port from environment or use default
    port = int(os.getenv("MCP_PORT", "8003"))
    host = os.getenv("MCP_HOST", "0.0.0.0")

    # Run with SSE transport for HTTP/StreamableHttp
    mcp.run(transport="sse", host=host, port=port)
