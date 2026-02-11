"""MCP Server for Confluence - supports SSE and streamable-http transports."""

from fastmcp import FastMCP
import json
import os
from typing import Dict, Any
from starlette.applications import Starlette
from starlette.routing import Mount
from .confluence_client import ConfluenceClient
from .config import get_config

config = get_config()
client = ConfluenceClient(config.base_url, config.username, config.api_token)

SERVER_NAME = "confluence-search"
SERVER_HOST = os.getenv("MCP_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("MCP_PORT", "8003"))

# Create MCP server
mcp = FastMCP(SERVER_NAME)


@mcp.tool()
def search_content(
    query: str,
    space_key: str | None = None,
    content_type: str = "page",
    limit: int = 10
) -> str:
    """Search content in Confluence by keywords."""
    cql_parts = [f'text ~ "{query}"']
    if space_key:
        cql_parts.append(f'space = "{space_key}"')
    if content_type and content_type != "all":
        cql_parts.append(f'type = "{content_type}"')
    cql = " AND ".join(cql_parts)
    result = client.search(cql=cql, limit=int(limit), expand=["space", "version"])
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def search_by_cql(cql: str, limit: int = 10, expand: list[str] | None = None) -> str:
    """Advanced search using CQL."""
    if expand is None:
        expand = ["space", "version"]
    result = client.search(cql=cql, limit=int(limit), expand=expand)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def get_page_content(page_id: str) -> str:
    """Get full content of a page by ID."""
    result = client.get_content(content_id=page_id, expand=["space", "version", "body.view"])
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def list_spaces(limit: int = 50) -> str:
    """Get list of available spaces."""
    result = client.get_spaces(limit=int(limit))
    return json.dumps(result, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    import uvicorn

    # Create SSE app (for Claude Code) - uses /messages endpoint
    sse_app = mcp.http_app(transport="sse")

    # Create streamable-http app (for SuperAssistant Proxy) - uses /mcp endpoint
    streamable_http_app = mcp.http_app(transport="streamable-http", path="/mcp")

    # Combine both apps by extracting routes
    # SSE app handles /sse and /messages
    # streamable-http app handles /mcp
    app = Starlette(
        routes=streamable_http_app.routes + sse_app.routes
    )

    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
