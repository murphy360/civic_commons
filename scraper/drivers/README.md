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

| Driver | Source Type | Notes |
|--------|-------------|-------|
| `civic_plus` | CivicPlus CMS | Agenda centers, HTML parsing |
| `aspnet_generic` | ASP.NET sites | Playwright-based for JS rendering |
| `rss` | RSS/Atom feeds | Universal fallback |
| `libcal` | LibCal/Springshare | Library events API |
| `civic_rec` | CivicRec | Parks & recreation |
| `metroparks` | Cleveland Metroparks | Regional parks |

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
