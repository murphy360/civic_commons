# /scraper

The background worker service that fetches data from configured sources.

## Architecture

```
/scraper
├── main.py              # Scheduler entrypoint
├── config.py            # Configuration loading (Pydantic)
├── models/              # Data models
│   ├── __init__.py
│   ├── event.py
│   └── document.py
├── drivers/             # Source-specific scrapers
│   ├── __init__.py
│   ├── base.py          # Abstract base class
│   ├── civic_plus.py
│   ├── aspnet_generic.py
│   ├── rss.py
│   └── libcal.py
├── pipeline/            # Processing pipeline
│   ├── __init__.py
│   ├── pdf.py           # PDF extraction
│   └── storage.py       # Database operations
└── utils/               # Shared utilities
    ├── __init__.py
    └── http.py          # HTTP client with rate limiting
```

## Adding a New Driver

1. Copy `drivers/_template.py` to `drivers/your_driver.py`
2. Implement the `BaseDriver` interface
3. Register in `drivers/__init__.py`
4. Use in YAML config: `driver: "your_driver"`

## Running Locally

```bash
# With Docker
docker-compose up commons-worker

# Without Docker (development)
cd scraper
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
python main.py
```

## Environment Variables

See `.env.example` in project root.
