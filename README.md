# Civic Commons

**A civic data aggregation platform that collects, indexes, and makes searchable public information from local government sources.**

Civic Commons scrapes meeting minutes, agendas, events, and documents from city websites, school boards, libraries, and other civic organizations—then exposes that data through a user-friendly web interface and an MCP (Model Context Protocol) server for LLM integration.

## ✨ Features

- 📅 **Event Aggregation** - Consolidates calendars from multiple civic sources
- 📄 **Document Indexing** - Full-text search across meeting minutes, agendas, PDFs
- 🎥 **Video Integration** - YouTube meeting recordings linked to events
- 🤖 **AI Summaries** - Automatic document summarization with Gemini AI
- 📜 **Legislation Tracking** - Extracts and tracks ordinances, resolutions across meetings
- 📰 **Newsletters** - Auto-generated daily/weekly/monthly digests
- 🔗 **MCP Server** - LLM-accessible API for AI assistants
- 🏙️ **Multi-City Support** - Configure multiple cities via YAML manifests
- 🐳 **Docker-First** - One command to run everything

## 🚀 Quick Start

```powershell
# 1. Clone and configure
git clone https://github.com/murphy360/civic_commons.git
cd civic_commons
Copy-Item .env.example .env
# Edit .env with your passwords and GEMINI_API_KEY

# 2. Start everything
docker-compose up -d

# 3. Access the apps
# Web:   http://localhost:3002
# Admin: http://localhost:3003
```

**That's it!** Database schema is auto-initialized. See [QUICKSTART.md](QUICKSTART.md) for details.

## 📁 Project Structure

```
civic_commons/
├── admin/          # Admin dashboard (Next.js) - source management
├── configs/        # City YAML configurations
├── scraper/        # Python worker service
│   ├── drivers/    # Source-specific scrapers (CivicPlus, LibCal, RSS, etc.)
│   ├── pipeline/   # Data processing (AI, storage, linking)
│   │   └── ai/     # Gemini-powered summarization
│   └── models/     # Pydantic data models
├── server/         # MCP server + REST API (Python)
├── shared/         # Shared TypeScript schema & types
├── web/            # Public web app (Next.js)
├── scripts/        # Database init & migrations
└── tests/          # Test suite
```

## 🏗️ Architecture

| Service | Container | Technology | Purpose |
|---------|-----------|------------|---------|
| **Web** | `commons-web` | Next.js 14 | Public search, browse, AI chat |
| **Admin** | `commons-admin` | Next.js 14 | Source management, monitoring |
| **Worker** | `commons-worker` | Python/APScheduler | Scheduled scraping & AI processing |
| **MCP Server** | `commons-mcp` | Python/FastMCP | LLM tool interface (stdio) |
| **API Server** | `commons-api` | Python/FastAPI | REST API for web/admin |
| **Database** | `db` | PostgreSQL 15 | Data storage with full-text search |

## 🔧 Environment Variables

Key variables in `.env`:

```bash
POSTGRES_PASSWORD=your_password      # Required
GEMINI_API_KEY=your_api_key          # For AI summaries
SCRAPER_INTERVAL=3600                # Seconds between scrapes
AI_QUEUE_INTERVAL_SECONDS=30         # AI processing frequency
```

## 📖 Documentation

- [QUICKSTART.md](QUICKSTART.md) - Get running in 5 minutes
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) - Architecture deep dive
- [configs/README.md](configs/README.md) - City configuration guide
- [scraper/README.md](scraper/README.md) - Worker service details
- [server/README.md](server/README.md) - MCP/API server details

## 🤝 Contributing

1. Check existing city configs in `configs/` for examples
2. Read `PROJECT_CONTEXT.md` for architecture decisions
3. Follow the Driver pattern in `scraper/drivers/` for new sources
4. Run `python scripts/check_monoliths.py` to check code health

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.
