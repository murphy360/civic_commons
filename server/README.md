# /server

The API layer providing both MCP (Model Context Protocol) for LLM integration and REST API for web apps.

## Architecture

```
/server
├── main.py              # FastMCP server entrypoint (stdio)
├── api_server.py        # FastAPI REST server
├── config.py            # Configuration loading (env vars + city YAML)
├── tools.py             # MCP tool definitions
├── chat.py              # AI chat with Gemini (configurable persona)
├── db.py                # Database queries
└── auth.py              # API key authentication
```

## Two Server Modes

### MCP Server (stdio transport)
Used by LLM clients (Claude, etc.) for direct tool access:
```bash
docker compose up commons-mcp
```

### REST API Server
Used by web/admin apps:
```bash
docker compose up commons-api
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_commons_calendar` | Get events within a date range |
| `search_commons_records` | Full-text search of documents |
| `get_event_details` | Get event with documents and sources |
| `get_document_content` | Get document text and summary |
| `get_assistant_manifest` | Get bot name and persona |
| `get_source_health` | Check status of data sources |

## REST API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/events` | GET | List events with filtering |
| `/events/{id}` | GET | Get event details |
| `/documents` | GET | List documents |
| `/documents/{id}` | GET | Get document details |
| `/chat` | POST | AI chat with configurable persona |
| `/health` | GET | Health check |

## Configurable Chat Persona

The chat service loads assistant configuration from the city's YAML config:

```yaml
# configs/twinsburg.yaml
assistant:
  name: "Wilcox"
  persona: "A helpful local historian..."
  
city_profile:
  name: "Twinsburg, OH"
```

This drives the AI chat system prompt, making the assistant name and personality configurable per deployment.

## Running

```bash
# MCP Server (Docker)
docker compose up commons-mcp

# API Server (Docker)
docker compose up commons-api

# Development (local)
cd server
pip install -r requirements.txt
python main.py          # MCP server
python api_server.py    # REST API
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | - | PostgreSQL connection string |
| `MCP_API_KEY` | - | API key for authentication |
| `MCP_PORT` | 8080 | Port for API server |
| `GEMINI_API_KEY` | - | For AI chat features |
| `DEFAULT_CONFIG` | twinsburg.yaml | City config file for persona |

## Authentication

- **MCP Server**: No auth (stdio transport, local only)
- **REST API**: `X-API-Key` header required (matches `MCP_API_KEY`)
