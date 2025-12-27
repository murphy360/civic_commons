# MCP Server

Model Context Protocol server for LLM integration and AI processing.

**Container:** `civic_commons_mcp` | **Port:** 8000

## Overview

This service provides:
1. **MCP Tools** - LLM-accessible tools via SSE transport
2. **AI Processing** - Document/video/event summarization endpoints
3. **PDF Extraction** - Text extraction from PDF documents

## Endpoints

### MCP Transport
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/sse` | GET | SSE stream for MCP tool calls |
| `/messages` | POST | MCP message handler |

### AI Summarization (called by Cascade)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/summarize_document` | POST | Generate document summary |
| `/summarize_video` | POST | Generate video summary |
| `/summarize_event` | POST | Generate event summary |
| `/generate_period_summary` | POST | Generate newsletter |

### Utility
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/cascade/{doc_id}/{event_id}/{city_id}` | POST | Trigger cascade |

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_commons_calendar` | Get events in date range |
| `search_commons_records` | Full-text document search |
| `get_event_details` | Event with linked documents |
| `get_document_content` | Document text and AI summary |
| `get_assistant_manifest` | Bot name/persona |
| `get_source_health` | Data source status |

## Dependencies

This service requires AI/PDF packages:
- `pymupdf`, `pymupdf4llm` - PDF processing
- `httpx` - Gemini API calls

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection |
| `GEMINI_API_KEY` | Google AI API key |
| `MCP_API_KEY` | API authentication key |

## Docker

```bash
docker compose build commons-mcp
docker compose up -d commons-mcp
docker compose logs -f commons-mcp
```
