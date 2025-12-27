# Civic Commons

**A civic data aggregation platform that collects, indexes, and makes searchable public information from local government sources.**

Civic Commons scrapes meeting minutes, agendas, events, and documents from city websites, school boards, libraries, and other civic organizations—then exposes that data through a user-friendly web interface and an MCP (Model Context Protocol) server for LLM integration.

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              CIVIC COMMONS SYSTEM                                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐            │
│  │   Web App       │     │   Admin App     │     │  External LLMs  │            │
│  │  (Next.js)      │     │  (Next.js)      │     │  (Claude, etc)  │            │
│  │  Port 3000      │     │  Port 3001      │     │                 │            │
│  └────────┬────────┘     └────────┬────────┘     └────────┬────────┘            │
│           │                       │                       │                      │
│           │ HTTP                  │ HTTP                  │ MCP/SSE              │
│           ▼                       ▼                       ▼                      │
│  ┌─────────────────────────────────────────────────────────────────┐            │
│  │                        API LAYER                                 │            │
│  │  ┌─────────────────┐              ┌─────────────────┐           │            │
│  │  │   API Server    │              │   MCP Server    │           │            │
│  │  │   (FastAPI)     │◄────────────►│   (FastAPI)     │           │            │
│  │  │   Port 8080     │   Internal   │   Port 8000     │           │            │
│  │  │                 │              │                 │           │            │
│  │  │  • Chat API     │              │  • Tool hosting │           │            │
│  │  │  • REST queries │              │  • AI Summary   │           │            │
│  │  └────────┬────────┘              │  • PDF Extract  │           │            │
│  │           │                       └────────┬────────┘           │            │
│  └───────────┼────────────────────────────────┼────────────────────┘            │
│              │                                │                                  │
│              │                                │                                  │
│  ┌───────────┼────────────────────────────────┼────────────────────┐            │
│  │           │      BACKGROUND WORKERS        │                    │            │
│  │           │                                │                    │            │
│  │  ┌────────▼────────┐              ┌────────▼────────┐          │            │
│  │  │     Scraper     │              │     Cascade     │          │            │
│  │  │    (Python)     │              │    (Python)     │          │            │
│  │  │                 │              │                 │          │            │
│  │  │  • Fetch events │   Triggers   │  • AI queue     │          │            │
│  │  │  • Download PDFs│─────────────►│  • Summaries    │          │            │
│  │  │  • Extract text │              │  • Newsletters  │          │            │
│  │  │  • Link docs    │              │                 │          │            │
│  │  └────────┬────────┘              └────────┬────────┘          │            │
│  │           │                                │                    │            │
│  └───────────┼────────────────────────────────┼────────────────────┘            │
│              │                                │                                  │
│              │         ┌──────────────────────┘                                  │
│              │         │                                                         │
│              ▼         ▼                                                         │
│  ┌─────────────────────────────────┐     ┌─────────────────────┐                │
│  │        PostgreSQL 15            │     │   External APIs     │                │
│  │                                 │     │                     │                │
│  │  • Events, Documents            │     │  • Gemini AI        │                │
│  │  • Legislation                  │     │  • City websites    │                │
│  │  • Activity logs                │     │  • YouTube          │                │
│  │  • Queue state                  │     │                     │                │
│  └─────────────────────────────────┘     └─────────────────────┘                │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## 📦 Services Overview

| Service | Container | Port | Technology | Responsibility |
|---------|-----------|------|------------|----------------|
| **Web** | `civic_commons_web` | 3000 | Next.js 14 | Public UI: search, browse, chat |
| **Admin** | `civic_commons_admin` | 3001 | Next.js 14 | Admin UI: sources, logs, queue |
| **API** | `civic_commons_api` | 8080 | FastAPI | REST API for frontends |
| **MCP** | `civic_commons_mcp` | 8000 | FastAPI | AI tools, summaries, LLM interface |
| **Scraper** | `civic_commons_scraper` | - | Python | Scheduled scraping, downloading |
| **Cascade** | `civic_commons_cascade` | - | Python | AI queue processing |
| **Database** | `civic_commons_db` | 5432 | PostgreSQL | Data persistence |

## 🔄 Data Flow

```
1. SCRAPE      Scraper fetches events/documents from city websites
                          ↓
2. DOWNLOAD    PDFs downloaded to shared volume
                          ↓
3. EXTRACT     Text extracted from PDFs
                          ↓
4. QUEUE       Items queued for AI processing
                          ↓
5. ANALYZE     Cascade calls MCP for AI summaries (Gemini)
                          ↓
6. SERVE       Web/Admin apps display processed data
```

## ✨ Features

- 📅 **Event Aggregation** - Consolidates calendars from multiple civic sources
- 📄 **Document Indexing** - Full-text search across meeting minutes, agendas, PDFs
- 🎥 **Video Integration** - YouTube meeting recordings linked to events
- 🤖 **AI Summaries** - Automatic document summarization with Gemini AI
- 📜 **Legislation Tracking** - Extracts and tracks ordinances, resolutions across meetings
- 📰 **Newsletters** - Auto-generated daily/weekly/monthly digests
- 🔗 **MCP Server** - LLM-accessible API for AI assistants
- 🏙️ **Multi-City Support** - Configure cities via YAML
- 🐳 **Docker-First** - One command to run everything

## 🚀 Quick Start

```powershell
# 1. Clone and configure
git clone https://github.com/murphy360/civic_commons.git
cd civic_commons
Copy-Item .env.example .env
# Edit .env with your passwords and GEMINI_API_KEY

# 2. Start everything
docker compose up -d

# 3. Access the apps
# Web:   http://localhost:3000
# Admin: http://localhost:3001
```

**That's it!** Database schema is auto-initialized. See [QUICKSTART.md](QUICKSTART.md) for details.

## 📁 Project Structure

```
civic_commons/
├── server/                 # All Python backend services
│   ├── services/
│   │   ├── api/            # REST API (FastAPI) - chat, queries
│   │   └── mcp/            # MCP server - AI tools, summaries
│   ├── workers/
│   │   ├── scraper/        # Scraper worker
│   │   │   ├── drivers/    # Source-specific scrapers
│   │   │   ├── pipeline/   # Processing pipeline
│   │   │   └── models/     # Data models
│   │   └── cascade/        # AI queue processor
│   └── shared/             # Shared Python utilities
├── web/                    # Public Next.js app
├── admin/                  # Admin Next.js app
├── shared/                 # Shared TypeScript (Drizzle schema)
├── configs/                # City YAML configurations
├── scripts/                # DB init & migrations
├── docs/                   # Architecture documentation
├── personas/               # User personas for design
└── tests/                  # Test suite
```

## 🔧 Environment Variables

Key variables in `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_PASSWORD` | ✅ | Database password |
| `MCP_API_KEY` | ✅ | API key for MCP server |
| `NEXTAUTH_SECRET` | ✅ | NextAuth session secret |
| `GEMINI_API_KEY` | ⚠️ | For AI summaries (optional) |
| `DEFAULT_CONFIG` | - | City config file (default: `twinsburg.yaml`) |
| `SCRAPER_INTERVAL` | - | Seconds between scrapes (default: 3600) |

## 📖 Documentation

| Document | Purpose |
|----------|---------|
| [QUICKSTART.md](QUICKSTART.md) | Get running in 5 minutes |
| [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) | Architecture deep dive |
| [docs/ARCHITECTURE_PHASE1.md](docs/ARCHITECTURE_PHASE1.md) | Phase 1 design decisions |
| [docs/QUEUE_SYSTEM.md](docs/QUEUE_SYSTEM.md) | Queue processing details |
| [configs/README.md](configs/README.md) | City configuration guide |
| [server/README.md](server/README.md) | Backend services overview |
| [personas/README.md](personas/README.md) | User personas |

## 🐳 Docker Commands

```powershell
# Start all services
docker compose up -d

# View logs
docker compose logs -f commons-scraper

# Restart a service
docker compose restart commons-mcp

# Rebuild after code changes
docker compose build commons-mcp; docker compose up -d commons-mcp

# Check service health
docker ps --format "table {{.Names}}\t{{.Status}}"
```

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.
