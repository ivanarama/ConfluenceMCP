"""MCP Server for Confluence - with custom HTTP endpoints for MCP SuperAssistant Proxy."""

from fastmcp import FastMCP
import json
import os
import uuid
from typing import Dict

from .confluence_client import ConfluenceClient
from .config import get_config

config = get_config()
client = ConfluenceClient(config.base_url, config.username, config.api_token)

SERVER_NAME = "confluence-search"
SERVER_HOST = os.getenv("MCP_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("MCP_PORT", "8003"))

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
    result = client.search(cql=cql, limit=limit, expand=["space", "version"])
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def search_by_cql(cql: str, limit: int = 10, expand: list[str] | None = None) -> str:
    """Advanced search using CQL."""
    if expand is None:
        expand = ["space", "version"]
    result = client.search(cql=cql, limit=limit, expand=expand)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def get_page_content(page_id: str) -> str:
    """Get full content of a page by ID."""
    result = client.get_content(content_id=page_id, expand=["space", "version", "body.view"])
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def list_spaces(limit: int = 50) -> str:
    """Get list of available spaces."""
    result = client.get_spaces(limit=limit)
    return json.dumps(result, indent=2, ensure_ascii=False)


def create_sse_response(data: Dict) -> any:
    """Создаёт SSE ответ из данных JSON-RPC"""
    from starlette.responses import Response
    sse_data = json.dumps(data, ensure_ascii=False)
    return Response(
        content=f"event: message\ndata: {sse_data}\n\n",
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@mcp.custom_route("/mcp", methods=["GET", "POST"])
async def mcp_endpoint(request) -> any:
    """Endpoint для MCP SuperAssistant Proxy с SSE форматом ответов."""
    from starlette.responses import Response

    # GET - возвращаем endpoint info
    if request.method == "GET":
        return Response(
            content="event: endpoint\ndata: /mcp\n\n",
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )

    # POST - обрабатываем JSON-RPC запросы
    try:
        req_data = await request.json()

        if not isinstance(req_data, dict):
            return create_sse_response({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request"}
            })

        method = req_data.get("method")
        req_id = req_data.get("id")

        # initialize
        if method == "initialize":
            return create_sse_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
                    "capabilities": {"tools": {}}
                }
            })

                # tools/list
        elif method == "tools/list":
            # Возвращаем инструменты с правильными схемами
            tools = [
                {
                    "name": "search_content",
                    "description": "Search content in Confluence by keywords.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Keywords to search for"},
                            "space_key": {"type": "string", "description": "Space key filter (optional)"},
                            "content_type": {"type": "string", "enum": ["page", "blogpost", "all"], "description": "Content type (default: page)"},
                            "limit": {"type": "integer", "description": "Max results (default: 10)", "default": 10}
                        },
                        "required": ["query"]
                    }
                },
                {
                    "name": "search_by_cql",
                    "description": "Advanced search using CQL.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "cql": {"type": "string", "description": "CQL query"},
                            "limit": {"type": "integer", "default": 10},
                            "expand": {"type": "array", "items": {"type": "string"}, "default": ["space", "version"]}
                        },
                        "required": ["cql"]
                    }
                },
                {
                    "name": "get_page_content",
                    "description": "Get full content of a page by ID.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "page_id": {"type": "string", "description": "Confluence page ID"}
                        },
                        "required": ["page_id"]
                    }
                },
                {
                    "name": "list_spaces",
                    "description": "Get list of available spaces.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "default": 50}
                        }
                    }
                }
            ]
            return create_sse_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": tools}
            })

        # tools/call
        elif method == "tools/call":
            params = req_data.get("params", {})
            name = params.get("name")
            arguments = params.get("arguments", {})

            try:
                tools_dict = await mcp.get_tools()
                if name in tools_dict:
                    tool = tools_dict[name]
                    if hasattr(tool, 'fn') and callable(tool.fn):
                        result = tool.fn(**arguments)
                        return create_sse_response({
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {"content": [{"type": "text", "text": str(result)}]}
                        })
                    else:
                        return create_sse_response({
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": -32603, "message": f"Tool {name} is not callable"}
                        })
                else:
                    return create_sse_response({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"Tool not found: {name}"}
                    })
            except Exception as e:
                return create_sse_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": f"Tool execution error: {str(e)}"}
                })

        # resources/list
        elif method == "resources/list":
            return create_sse_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"resources": []}
            })

        # prompts/list
        elif method == "prompts/list":
            return create_sse_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"prompts": []}
            })

        # notifications/*
        elif method and method.startswith("notifications/"):
            if req_id is not None:
                return create_sse_response({"jsonrpc": "2.0", "id": req_id, "result": {}})
            else:
                return Response(content=": \n\n", media_type="text/event-stream")

        # ping
        elif method == "ping":
            return create_sse_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"status": "ok"}
            })

        else:
            return create_sse_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}
            })

    except json.JSONDecodeError:
        return create_sse_response({
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": "Parse error"}
        })
    except Exception as e:
        return create_sse_response({
            "jsonrpc": "2.0",
            "id": req_data.get("id") if 'req_data' in locals() else None,
            "error": {"code": -32603, "message": f"Internal error: {str(e)}"}
        })


if __name__ == "__main__":
    mcp.run(transport="sse", host=SERVER_HOST, port=SERVER_PORT)
