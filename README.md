# Civic Commons

**A civic data aggregation platform that collects, indexes, and makes searchable public information from local government sources.**

Civic Commons scrapes meeting minutes, agendas, events, and documents from city websites, school boards, libraries, and other civic organizations—then exposes that data through a user-friendly web interface and an MCP (Model Context Protocol) server for LLM integration.

## ✨ Features

- 📅 **Event Aggregation** - Consolidates calendars from multiple civic sources
- 📄 **Document Indexing** - Full-text search across meeting minutes, agendas, PDFs
- 🤖 **LLM Integration** - MCP server enables AI assistants to query civic data
- 🔔 **Alerts & Newsletters** - Subscribe to topics and get notified of new content
- 🏙️ **Multi-City Support** - Configure multiple cities via YAML manifests
- 🐳 **Docker-First** - One command to run everything

## 🚀 Quick Start

```powershell
# 1. Clone and configure
git clone https://github.com/your-org/civic_commons.git
cd civic_commons
Copy-Item .env.example .env
# Edit .env with your passwords/secrets

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
├── admin/          # Admin dashboard (Next.js)
├── configs/        # City YAML configurations
├── personas/       # User personas for validation
├── scraper/        # Python worker service
│   ├── drivers/    # Source-specific scrapers
│   └── pipeline/   # Data processing pipeline
├── server/         # MCP server (Python/FastMCP)
├── shared/         # Shared schema & types
├── web/            # Public web app (Next.js)
├── scripts/        # Database init scripts
└── tests/          # Test suite
```

## 🏗️ Architecture

| Service | Technology | Purpose |
|---------|------------|---------|
| Web | Next.js 14, shadcn/ui | Public-facing search & browse |
| Admin | Next.js 14, shadcn/ui | Source management, monitoring |
| Worker | Python, APScheduler | Scheduled scraping jobs |
| MCP Server | Python, FastMCP | LLM tool interface |
| Database | PostgreSQL 15 | Data storage with full-text search |

All services run in Docker containers and communicate over an internal network.

## 📖 Documentation

- [QUICKSTART.md](QUICKSTART.md) - Get running in 5 minutes
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) - Architecture deep dive
- [configs/README.md](configs/README.md) - City configuration guide
- [scraper/drivers/README.md](scraper/drivers/README.md) - Writing custom drivers

## 🔧 Development

For active development with hot reload:

```powershell
# Database in Docker, apps locally
docker-compose up db

# In separate terminals:
cd web && npm install && npm run dev
cd admin && npm install && npm run dev
cd scraper && pip install -r requirements.txt && python main.py
```

## 🤝 Contributing

1. Check `personas/` to understand user needs
2. Read `PROJECT_CONTEXT.md` for architecture decisions
3. Follow the Driver/Manifest pattern for new data sources
4. Test against the Twinsburg, OH reference configuration

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.
