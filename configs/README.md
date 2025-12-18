# /configs

City configuration files in YAML format. Each file defines a complete deployment including assistant persona, CivicPlus platform settings, and data sources.

## Usage

1. Copy `_template.yaml` to `<your-city>.yaml`
2. Fill in your city's details and assistant persona
3. Configure CivicPlus category CIDs (if using CivicPlus drivers)
4. Configure data sources with appropriate drivers
5. Set `DEFAULT_CONFIG=your-city.yaml` in `.env`
6. Restart the services

## File Structure

```yaml
# =============================================================================
# IDENTITY
# =============================================================================
city_profile:
  name: "City Name, ST"
  zip: "12345"
  timezone: "America/New_York"

# =============================================================================
# ASSISTANT PERSONALITY
# =============================================================================
assistant:
  name: "City Bot"                    # Name shown in chat UI
  persona: "Friendly civic assistant" # Personality for AI responses

# =============================================================================
# CIVICPLUS PLATFORM SETTINGS (if using CivicPlus drivers)
# =============================================================================
civicplus:
  # Agenda Center category CIDs (site-specific, found in RSS feed URLs)
  agenda_categories:
    city_council: "City-Council-2"
    planning_commission: "Planning-Commission-4"
  
  # Calendar category CIDs (site-specific)
  calendar_categories:
    main: "Main-Calendar-14"
    all: "All-calendar.xml"

# =============================================================================
# PUBLIC DATA SOURCES
# =============================================================================
sources:
  - name: "City Council"
    driver: "civic_plus"        # Driver to use
    enabled: true               # Toggle source on/off
    schedule: "0 */6 * * *"     # Cron schedule
    params:                     # Driver-specific params
      base_url: "https://..."
      categories: ["city_council"]
```

## Available Drivers

| Driver | Use Case |
|--------|----------|
| `civic_plus` | CivicPlus Agenda Center (HTML scraping) |
| `civic_plus_rss` | CivicPlus Agenda Center RSS feeds |
| `civic_plus_calendar` | CivicPlus calendar module |
| `civicplus_document_center` | CivicPlus Document Center |
| `libcal` | Library calendars (LibCal/Springshare) |
| `rss` | Generic RSS feeds |
| `icalendar` | iCalendar (.ics) feeds |
| `youtube_channel` | YouTube channel videos |
| `tcsd_agendas` | TCSD school board (custom) |
| `aspnet_generic` | ASP.NET-based sites (Playwright) |

## Finding CivicPlus Category CIDs

CivicPlus category IDs (CIDs) are site-specific and found in RSS feed URLs:

1. Go to your city's AgendaCenter (e.g., `https://www.mycity.gov/AgendaCenter`)
2. Click the RSS icon for a category
3. The URL contains the CID: `.../RSS/City-Council-2` → CID is `City-Council-2`

## Adding a New City

```bash
cp _template.yaml mycity.yaml
# Edit mycity.yaml with your city's configuration
docker compose restart commons-worker commons-api
```

The worker automatically loads all YAML files in this directory on startup.

## Configuration Loading

- **Worker Service**: Loads source definitions from YAML
- **API Server**: Loads `assistant.name`, `assistant.persona`, and `city_profile` for chat
- Environment variable `DEFAULT_CONFIG` specifies which YAML file to use (default: `twinsburg.yaml`)
