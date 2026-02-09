# MCP Server for Confluence Search

MCP (Model Context Protocol) server for searching internal Confluence documentation. Uses **StreamableHttp/SSE transport** for HTTP-based communication with **Basic Authentication**.

## Features

- **Keyword Search**: Search content by keywords with optional space and content type filters
- **CQL Search**: Advanced search using Confluence Query Language
- **Page Content**: Retrieve full page content by ID
- **Space Listing**: List all available Confluence spaces
- **HTTP/SSE Transport**: Runs as HTTP server with Server-Sent Events
- **Basic Auth**: Uses username + password (local) or email + API token (cloud)

## Installation

### Option 1: Docker (Recommended)

#### 1. Create Environment File

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:
```
CONFLUENCE_BASE_URL=https://your-domain.atlassian.net/wiki
CONFLUENCE_USERNAME=your-email@example.com
CONFLUENCE_API_TOKEN=your-api-token-here
MCP_PORT=8003
```

#### 2. Build and Run with Docker Compose

```bash
docker-compose up -d
```

The server will be available at `http://localhost:8003/sse`

### Option 2: Local Installation

#### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

## Getting Confluence Credentials

### For Local/On-Premise Confluence

1. **Get Confluence URL** — usually `http://localhost:8090/wiki` or your server URL
2. **Use your username and password** — the same credentials you use to login to Confluence

Example `.env`:
```
CONFLUENCE_BASE_URL=http://localhost:8090/wiki
CONFLUENCE_USERNAME=admin
CONFLUENCE_API_TOKEN=your-password
```

### For Atlassian Cloud

If you're using Atlassian Cloud, you need an API token:
1. Go to: https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Use your email as username and the API token as password

## Usage

### Running the Server

#### Docker (Recommended):
```bash
docker-compose up
```

The server starts on `http://localhost:8003/sse`

#### Local:
```bash
python -m confluence_mcp.server
```

Or set custom port:
```bash
MCP_PORT=8080 python -m confluence_mcp.server
```

### Available Tools

#### `search_content`
Basic keyword search with optional filters.

**Parameters:**
- `query` (required): Keywords to search for
- `space_key` (optional): Filter by space key
- `content_type` (optional): Content type - "page", "blogpost", or "all" (default: "page")
- `limit` (optional): Max results, default 10 (max 100)

**Example:**
```json
search_content(query="API documentation", space_key="DEV", limit=5)
```

#### `search_by_cql`
Advanced search using CQL (Confluence Query Language).

**Parameters:**
- `cql` (required): CQL query string
- `limit` (optional): Max results, default 10
- `expand` (optional): Fields to expand (space, version, container, etc.)

**Example:**
```json
search_by_cql(cql='space = "DEV" AND type = "page" AND created > "2024-01-01"')
```

#### `get_page_content`
Get full content of a specific page.

**Parameters:**
- `page_id` (required): Confluence page ID

**Example:**
```json
get_page_content(page_id="123456")
```

#### `list_spaces`
List all available Confluence spaces.

**Parameters:**
- `limit` (optional): Max spaces to return, default 50

**Example:**
```json
list_spaces(limit=100)
```

## Claude Desktop Integration

### Docker (Recommended)

Add to `C:\Users\ibrog\AppData\Roaming\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "confluence": {
      "url": "http://localhost:8003/sse",
      "transport": "sse"
    }
  }
}
```

Start the container:
```bash
docker-compose up -d
```

### Local Python

Add to `C:\Users\ibrog\AppData\Roaming\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "confluence": {
      "url": "http://localhost:8003/sse",
      "transport": "sse"
    }
  }
}
```

Start the server:
```bash
python -m confluence_mcp.server
```

### Configuration Options

You can customize the port and host via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_PORT` | `8003` | Port for the MCP server |
| `MCP_HOST` | `0.0.0.0` | Host to bind to |

After updating the config:
1. Start the server (Docker or local)
2. Restart Claude Desktop
3. In a new chat, use commands like "Search Confluence for API documentation"
4. Claude will automatically use the available tools

## CQL Reference

Common CQL patterns:

| Query | Description |
|-------|-------------|
| `text ~ "keyword"` | Search by keyword |
| `space = "KEY"` | Filter by space |
| `type = "page"` | Filter by content type |
| `creator = "user@example.com"` | Filter by creator |
| `created > "2024-01-01"` | Filter by creation date |
| `lastmodified > "-30d"` | Modified in last 30 days |

Combine with `AND`/`OR`:

```
space = "DEV" AND type = "page" AND (text ~ "API" OR text ~ "REST")
```

## Project Structure

```
src/confluence_mcp/
├── __init__.py          # Package initialization
├── server.py            # MCP server with SSE transport
├── confluence_client.py # Confluence API client with Basic Auth
└── config.py            # Configuration management
```

## Docker

### Build
```bash
docker build -t confluence-mcp .
```

### Run
```bash
docker run -p 8003:8003 --env-file .env confluence-mcp
```

### With Docker Compose
```bash
docker-compose up -d
docker-compose logs -f
docker-compose down
```

## Requirements

- Python 3.10+
- Confluence access (local or cloud, with Basic Auth)
- Docker (optional, for containerized deployment)
