# /configs

City configuration files in YAML format. Each file defines a complete deployment.

## Usage

1. Copy `_template.yaml` to `<your-city>.yaml`
2. Fill in your city's details
3. Configure data sources with appropriate drivers
4. Restart the worker service

## File Structure

```yaml
city_profile:
  name: "City Name, ST"
  zip: "12345"
  timezone: "America/New_York"

assistant:
  name: "City Bot"
  persona: "Friendly civic assistant"

sources:
  - name: "City Council"
    driver: "civic_plus"        # Driver to use
    schedule: "0 */6 * * *"     # Cron schedule
    params:                     # Driver-specific params
      base_url: "https://..."
      categories: ["city_council"]
```

## Available Drivers

| Driver | Use Case |
|--------|----------|
| `civic_plus` | CivicPlus Agenda Center |
| `civic_plus_rss` | CivicPlus RSS feeds |
| `civic_plus_calendar` | CivicPlus calendar module |
| `civicplus_document_center` | CivicPlus Document Center |
| `libcal` | Library calendars (LibCal) |
| `rss` | Generic RSS feeds |
| `icalendar` | iCalendar (.ics) feeds |
| `youtube_channel` | YouTube channel videos |
| `tcsd_agendas` | TCSD school board (custom) |
| `aspnet_generic` | ASP.NET-based sites |

## Adding a New City

```bash
cp _template.yaml mycity.yaml
# Edit mycity.yaml with your city's configuration
docker-compose restart commons-worker
```

The worker automatically loads all YAML files in this directory on startup.

## Example Source

```yaml
sources:
  - name: "City Council"
    driver: "civic_plus"
    schedule: "0 8 * * *"    # Daily at 8 AM
    params:
      base_url: "https://www.mycity.gov"
      module: "agenda"
      categories:
        - "city_council"
        - "planning_commission"
```
