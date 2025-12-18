# /scraper

The background worker service that fetches data from configured sources and processes it with AI.

## Architecture

```
/scraper
├── main.py              # Worker entrypoint with APScheduler
├── config.py            # Configuration loading (Pydantic)
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
├── pipeline/            # Processing pipeline
│   ├── storage.py       # Database operations
│   ├── scraper.py       # Scrape execution
│   ├── document_linker.py   # Event-document linking
│   ├── ai_queue.py      # AI processing orchestration
│   ├── ai_processor.py  # AI task processing
│   ├── downloader.py    # PDF/file downloading
│   ├── backfill.py      # Historical data backfill
│   ├── pdf.py           # PDF text extraction
│   └── ai/              # AI-powered features
│       ├── client.py        # Gemini API client
│       ├── summarizer.py    # Event summarization
│       ├── doc_summarizer.py    # Document summarization
│       └── newsletter.py    # Newsletter generation
└── scripts/             # Utility scripts
```

## Key Features

- **Scheduled Scraping** - APScheduler runs scrapes at configured intervals
- **AI Summaries** - Gemini-powered document and event summarization
- **Legislation Extraction** - Identifies ordinances/resolutions in documents
- **Document Linking** - Links documents to events by date and AI matching
- **Newsletter Generation** - Auto-generates daily/weekly/monthly digests
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
docker compose up commons-worker

# Without Docker (development)
cd scraper
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
python main.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | - | PostgreSQL connection string |
| `GEMINI_API_KEY` | - | Google Gemini API key |
| `DEFAULT_CONFIG` | twinsburg.yaml | City config file to load |
| `SCRAPER_INTERVAL` | 3600 | Seconds between scrape cycles |
| `AI_QUEUE_INTERVAL_SECONDS` | 30 | Seconds between AI queue checks |
| `AI_QUEUE_BATCH_SIZE` | 1 | Documents to process per AI cycle |
| `RUN_ON_STARTUP` | false | Run initial scrape on start |
| `LOG_LEVEL` | INFO | Logging level |

## Docker

```bash
# Build and run
docker compose build commons-worker
docker compose up -d commons-worker

# View logs
docker compose logs -f commons-worker
```
