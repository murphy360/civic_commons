# /server

The Python backend containing all services and workers for Civic Commons.

## 🏗️ Architecture

```
/server
├── services/               # HTTP-facing services
│   ├── api/               # REST API for web/admin frontends
│   │   ├── api_server.py  # FastAPI server (port 8080)
│   │   └── Dockerfile
│   └── mcp/               # MCP server for LLM tools + AI processing
│       ├── sse_server.py  # FastAPI + SSE (port 8000)
│       └── Dockerfile
├── workers/               # Background workers (no HTTP)
│   ├── scraper/          # Data collection worker
│   │   ├── main.py       # APScheduler entrypoint
│   │   ├── drivers/      # Source-specific scrapers
│   │   ├── pipeline/     # Processing pipeline + AI modules
│   │   └── Dockerfile
│   └── cascade/          # AI queue processor
│       ├── cascade_service.py
│       └── Dockerfile
├── shared/               # Shared Python utilities
│   └── activity_log.py   # Database activity logging
├── requirements.txt      # Base dependencies (used by services)
└── [legacy files]        # Files being migrated (main.py, tools.py, etc.)
```

## 📦 Services

### API Server (`services/api/`)
**Container:** `civic_commons_api` | **Port:** 8080

REST API consumed by Web and Admin frontends.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/events` | GET | List events with filtering |
| `/events/{id}` | GET | Event details with documents |
| `/documents` | GET | List documents |
| `/documents/{id}` | GET | Document details |
| `/chat` | POST | AI chat (Gemini) with city persona |
| `/health` | GET | Health check |

**Key Features:**
- Loads city persona from YAML config (`assistant.name`, `assistant.persona`)
- Streams chat responses via SSE
- CORS configured for frontend origins

### MCP Server (`services/mcp/`)
**Container:** `civic_commons_mcp` | **Port:** 8000

Hosts MCP tools for LLM integration AND AI processing capabilities.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/sse` | GET | MCP tool stream (SSE) |
| `/messages` | POST | MCP message handler |
| `/summarize_document` | POST | Generate AI document summary |
| `/summarize_video` | POST | Generate AI video summary |
| `/summarize_event` | POST | Generate AI event summary |
| `/generate_period_summary` | POST | Generate newsletter/digest |
| `/health` | GET | Health check |

**MCP Tools Exposed:**
- `get_commons_calendar` - Events in date range
- `search_commons_records` - Full-text document search
- `get_event_details` - Event with linked documents
- `get_document_content` - Document text and AI summary
- `get_assistant_manifest` - Bot name/persona
- `get_source_health` - Data source status

**AI Capabilities:**
- PDF text extraction (`pymupdf4llm`)
- Document summarization (Gemini)
- Video transcript summarization (YouTube)
- Newsletter generation

## ⚙️ Workers

### Scraper Worker (`workers/scraper/`)
**Container:** `civic_commons_scraper`

Scheduled data collection from civic sources.

**Responsibilities:**
- Fetch events from city websites (via drivers)
- Download PDF documents
- Extract text from PDFs
- Link documents to events
- Queue items for AI processing

**NOT responsible for:**
- AI summarization (delegated to Cascade → MCP)

See [workers/scraper/README.md](workers/scraper/README.md) for details.

### Cascade Worker (`workers/cascade/`)
**Container:** `civic_commons_cascade`

Background AI queue processor.

**Responsibilities:**
- Poll database for items needing AI analysis
- Call MCP server endpoints for summarization
- Process in dependency order (docs → events → summaries)
- Log AI activities to activity_log table

**Processing Order:**
1. Documents with `ai_summary IS NULL`
2. Videos with `ai_summary IS NULL`
3. Events with documents but no summary
4. Period summaries (weekly/monthly)

See [workers/cascade/README.md](workers/cascade/README.md) for details.

## 🔧 Dependencies

### Base Requirements (`requirements.txt`)
Used by API and MCP services:
- `fastapi`, `uvicorn` - Web framework
- `asyncpg` - PostgreSQL async driver
- `httpx` - HTTP client
- `mcp` - Model Context Protocol SDK
- `pymupdf`, `pymupdf4llm` - PDF processing (MCP only)

### Scraper Requirements (`workers/scraper/requirements.txt`)
- `APScheduler` - Job scheduling
- `beautifulsoup4`, `lxml` - HTML parsing
- `playwright` - Browser automation
- `feedparser` - RSS parsing

## 🐳 Docker

Each service has its own Dockerfile:

```powershell
# Build specific service
docker compose build commons-mcp

# Rebuild and restart
docker compose build commons-api; docker compose up -d commons-api

# View logs
docker compose logs -f commons-scraper

# Check health
docker ps --format "table {{.Names}}\t{{.Status}}"
```

## 📊 Service Communication

```
┌─────────────┐     HTTP      ┌─────────────┐
│   Scraper   │──────────────►│     MCP     │
└─────────────┘               └──────┬──────┘
       │                             │
       │                             │ AI APIs
       │                             ▼
       │                      ┌─────────────┐
       │         SQL          │   Gemini    │
       └─────────────────────►│   YouTube   │
                              └─────────────┘
       
┌─────────────┐     HTTP      ┌─────────────┐
│   Cascade   │──────────────►│     MCP     │
└─────────────┘               └─────────────┘
       │
       │ SQL (queue state)
       ▼
┌─────────────┐
│  PostgreSQL │
└─────────────┘
```

## 🔐 Environment Variables

| Variable | Service | Description |
|----------|---------|-------------|
| `DATABASE_URL` | All | PostgreSQL connection |
| `GEMINI_API_KEY` | MCP, API | Google AI key |
| `MCP_API_KEY` | MCP, API | Internal API authentication |
| `MCP_URL` | Scraper, Cascade | MCP server URL |
| `DEFAULT_CONFIG` | API | City YAML file |
