# /scraper/drivers

Scrapers implementing the `BaseDriver` interface. One file per source type.

## Architecture

All drivers inherit from `BaseDriver` and implement the `fetch()` method.

```python
class BaseDriver(ABC):
    @abstractmethod
    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch events and documents from the source."""
        pass
```

## Available Drivers

| Driver | File | Source Type | Notes |
|--------|------|-------------|-------|
| `civic_plus` | `civic_plus.py` | CivicPlus Agenda Center | HTML scraping, ~500 lines |
| `civic_plus_rss` | `civic_plus_rss.py` | CivicPlus RSS feeds | Uses civicplus_utils.py |
| `civic_plus_calendar` | `civic_plus_calendar.py` | CivicPlus Calendar | Uses civicplus_utils.py |
| `civicplus_document_center` | `civicplus_document_center.py` | CivicPlus Document Center | Document archive scraping |
| `aspnet_generic` | `aspnet_generic.py` | ASP.NET sites | Playwright-based for JS rendering |
| `rss` | `rss.py` | RSS/Atom feeds | Universal fallback |
| `libcal` | `libcal.py` | LibCal/Springshare | Library events API |
| `icalendar` | `icalendar_driver.py` | iCalendar feeds | .ics file parsing |
| `youtube_channel` | `youtube_channel.py` | YouTube channels | Video metadata extraction |
| `tcsd_agendas` | `tcsd_agendas.py` | TCSD school board | Custom school board driver |

## Shared Utilities

### `civicplus_utils.py`

Shared utilities for CivicPlus drivers (~250 lines):

- **Date Parsing** - Extract dates from titles, URLs, compressed formats
- **Type Inference** - Infer `EventType` and `DocumentType` from text
- **URL Validation** - Validate document URLs vs navigation pages
- **Title Cleaning** - Clean up meeting titles for display
- **Module Constants** - CivicPlus module IDs (consistent across all sites)

```python
from civicplus_utils import (
    extract_date_from_title,
    extract_date_from_url,
    infer_event_type,
    infer_doc_type,
    is_document_url,
    clean_meeting_title,
    CIVICPLUS_MODULES,
)
```

**Note**: Category CIDs (like "City-Council-2") are site-specific and configured in the city's YAML config file under `civicplus.agenda_categories` and `civicplus.calendar_categories`.

## Adding a New Driver

1. Copy `_template.py` to `your_driver.py`
2. Implement the `fetch()` method
3. Add to `__init__.py` registry
4. Add tests in `/tests/scraper/drivers/`

## Testing Drivers

```bash
# Test a specific driver
python -m pytest tests/scraper/drivers/test_civic_plus.py

# Test with a real config (dry run)
python -m scraper.drivers.civic_plus --config configs/twinsburg.yaml --dry-run
```
