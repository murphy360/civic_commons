# /server

The Model Context Protocol (MCP) server that provides an LLM-accessible API.

## Architecture

```
/server
├── main.py              # FastMCP entrypoint
├── config.py            # Configuration loading
├── tools.py             # MCP tool definitions
├── db.py                # Database queries
└── auth.py              # API key authentication
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_commons_calendar` | Get events within a date range |
| `search_commons_records` | Full-text search of documents |
| `get_assistant_manifest` | Get bot name and persona |
| `get_source_health` | Check status of data sources |

## Running

```bash
# With Docker
docker-compose up commons-mcp

# Without Docker (development)
cd server
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Authentication

All requests require an `X-API-Key` header matching the `MCP_API_KEY` environment variable.

## Environment Variables

- `MCP_API_KEY` - Required API key for authentication
- `MCP_PORT` - Port to listen on (default: 8080)
- `DATABASE_URL` - PostgreSQL connection string
