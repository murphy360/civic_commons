# /scraper

The background worker service that fetches data from configured civic sources.

## 🎯 Responsibilities

**This service IS responsible for:**
- ✅ Fetching events from city websites (via drivers)
- ✅ Downloading PDF documents to shared storage
- ✅ Extracting text from PDFs
- ✅ Linking documents to events by date/title
- ✅ Queuing items for AI processing
- ✅ Logging activities to the activity_log table

**This service is NOT responsible for:**
- ❌ AI summarization (delegated to Cascade → MCP)
- ❌ Newsletter generation (handled by MCP)

## Architecture

```
/scraper
├── main.py              # Worker entrypoint with APScheduler
├── config.py            # Configuration loading (Pydantic)
├── mcp_client.py        # HTTP client for MCP server
├── models/              # Data models
│   ├── event.py         # Event model
│   └── document.py      # Document model
├── drivers/             # Source-specific scrapers
│   ├── base.py              # Abstract base class
│   ├── civic_plus.py        # CivicPlus Agenda Center (HTML)
│   ├── civic_plus_rss.py    # CivicPlus Agenda Center (RSS)
│   ├── civic_plus_calendar.py # CivicPlus calendar module
│   ├── civicplus_document_center.py # Document Center
│   ├── civicplus_utils.py   # Shared CivicPlus utilities
│   ├── libcal.py            # Library calendar (LibCal)
│   ├── rss.py               # Generic RSS
│   ├── icalendar_driver.py  # iCalendar feeds
│   ├── youtube_channel.py   # YouTube channel scraper
│   ├── tcsd_agendas.py      # TCSD school board
│   └── aspnet_generic.py    # ASP.NET sites (Playwright)
└── pipeline/            # Processing pipeline
    ├── storage.py       # Database operations
    ├── scraper.py       # Scrape execution
    ├── queue_manager.py # Unified queue management
    ├── queue_processor.py   # Queue processing loop
    ├── document_linker.py   # Event-document linking
    ├── downloader.py    # PDF/file downloading
    ├── pdf.py           # PDF text extraction
    ├── activity_logger.py   # Activity logging
    └── ai/              # AI modules (used by MCP, not scraper)
        ├── client.py        # Gemini API client
        ├── doc_summarizer.py    # Document summarization
        └── summary_generator.py # Newsletter generation
```

## Key Features

- **Scheduled Scraping** - APScheduler runs scrapes at configured intervals
- **Document Linking** - Links documents to events by date and title matching
- **Queue Management** - Unified queue for download, extraction, and AI tasks
- **Manual Triggers** - Admin can trigger scrapes via database flags

## CivicPlus Drivers

The CivicPlus family of drivers share common utilities in `civicplus_utils.py`:

| Driver | Use Case | Lines |
|--------|----------|-------|
| `civic_plus.py` | HTML scraping of Agenda Center | ~500 |
| `civic_plus_rss.py` | RSS feed parsing | ~580 |
| `civic_plus_calendar.py` | Calendar module scraping | ~430 |
| `civicplus_utils.py` | Shared date parsing, type inference | ~250 |

**Note**: CivicPlus category CIDs are site-specific and configured in the city's YAML config under `civicplus.agenda_categories` and `civicplus.calendar_categories`.

## Adding a New Driver

1. Copy `drivers/_template.py` to `drivers/your_driver.py`
2. Implement the `BaseDriver` interface
3. Register in `drivers/__init__.py`
4. Use in YAML config: `driver: "your_driver"`

## Running

```bash
# With Docker (recommended)
docker compose up commons-scraper

# Without Docker (development)
cd server/workers/scraper
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
python main.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | - | PostgreSQL connection string |
| `MCP_URL` | - | MCP server URL for event tools |
| `CONFIG_DIR` | /app/configs | Directory with city YAML files |
| `SCRAPER_INTERVAL` | 3600 | Seconds between scrape cycles |
| `RUN_ON_STARTUP` | false | Run initial scrape on start |
| `LOG_LEVEL` | INFO | Logging level |

## Docker

```bash
# Build and run
docker compose build commons-scraper
docker compose up -d commons-scraper

# View logs
docker compose logs -f commons-scraper
```
