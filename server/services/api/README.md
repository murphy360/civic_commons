# API Server

REST API for web and admin frontends.

**Container:** `civic_commons_api` | **Port:** 8080

## Overview

This service provides the REST API consumed by the Web and Admin Next.js applications. It handles:
- Event and document queries
- AI chat with configurable city persona
- Health checks

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/events` | GET | List events with filtering |
| `/events/{id}` | GET | Event details with documents |
| `/documents` | GET | List documents |
| `/documents/{id}` | GET | Document details |
| `/chat` | POST | AI chat (streams via SSE) |
| `/health` | GET | Health check |

## Chat Persona

The chat endpoint uses the city's YAML configuration for personality:

```yaml
# configs/twinsburg.yaml
assistant:
  name: "Wilcox"
  persona: "A helpful local historian who knows Twinsburg..."
```

This drives the Gemini system prompt, making the chat assistant configurable per deployment.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection |
| `GEMINI_API_KEY` | Google AI API key |
| `MCP_API_KEY` | API authentication key |
| `DEFAULT_CONFIG` | City YAML file (e.g., `twinsburg.yaml`) |
| `API_CORS_ORIGINS` | Allowed CORS origins |

## Docker

```bash
docker compose build commons-api
docker compose up -d commons-api
docker compose logs -f commons-api
```

## Authentication

API endpoints require `X-API-Key` header matching `MCP_API_KEY` environment variable.
