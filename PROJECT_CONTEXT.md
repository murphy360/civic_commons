Project Context: Civic Commons
1. Vision
Civic Commons is an open-source, Dockerized platform that aggregates disparate civic data (councils, school boards, libraries, parks) into a unified "City Intelligence" layer. It provides an LLM-accessible API to query upcoming events, search public records, and answer questions about local governance.

2. Core Architecture
The system relies on a Driver/Manifest pattern. The code is generic; the city logic is configuration.

A. The Configuration (/configs/twinsburg.yaml)
Every deployment is defined by a YAML manifest. This is where the bot's name is set.

YAML

# Identity
city_profile:
  name: "Twinsburg, OH"
  zip: "44087"
  timezone: "America/New_York"

# The "Personality"
assistant:
  name: "Wilcox"  # Default name, configurable per deployment
  persona: "A helpful local historian who values accuracy and community context."

# The Data Sources
# Public sources (government, civic)
sources:
  - name: "City Council"
    driver: "civic_plus"
    schedule: "0 6 * * *"  # Cron: Daily at 6 AM
    params:
      base_url: "https://www.mytwinsburg.com"
      agenda_center_id: "5"
    retry:
      max_attempts: 3
      backoff_seconds: 60
    rate_limit:
      delay_seconds: 2
      max_concurrent: 1

  - name: "School Board"
    driver: "aspnet_generic"
    schedule: "0 */4 * * *"  # Every 4 hours
    params:
      url: "https://www.twinsburg.k12.oh.us/meetingsandagendas.aspx"
    rate_limit:
      delay_seconds: 3        # Playwright is heavier
      max_concurrent: 1

  - name: "Public Library"
    driver: "libcal"
    schedule: "0 7 * * *"
    params:
      library_id: "twinsburg"
    rate_limit:
      delay_seconds: 2

  - name: "Historical Society"
    driver: "rss"              # Or custom if they have unique site
    schedule: "0 8 * * *"
    params:
      feed_url: "https://twinsburghistoricalsociety.org/events/feed"
    rate_limit:
      delay_seconds: 2
      max_concurrent: 1

  - name: "Parks & Recreation"
    driver: "civic_rec"        # Common parks/rec software
    schedule: "0 6 * * *"
    params:
      base_url: "https://www.mytwinsburg.com/parks"
    rate_limit:
      delay_seconds: 2
      max_concurrent: 1

  - name: "Cleveland Metroparks"
    driver: "metroparks"
    schedule: "0 5 * * *"      # Early AM, less traffic
    params:
      region: "cleveland"
      # Filter to nearby reservations
      locations: ["bedford", "brecksville", "south-chagrin"]
    rate_limit:
      delay_seconds: 2
      max_concurrent: 1

# Private/optional sources (community, business)
private_sources:
  - name: "Chamber of Commerce"
    driver: "rss"
    enabled: false             # Opt-in, disabled by default
    schedule: "0 8 * * *"
    params:
      feed_url: "https://twinsburgchamber.com/events/feed"
    rate_limit:
      delay_seconds: 1

  - name: "Community Facebook Groups"
    driver: "facebook_events"
    enabled: false             # Requires API key
    schedule: "0 */6 * * *"
    params:
      group_ids: ["twinsburg-community"]
    rate_limit:
      delay_seconds: 5         # Respect FB rate limits
      max_concurrent: 1
B. The Container Stack
We use a 5-Service Microservice architecture in docker-compose.yml.

db (PostgreSQL 15)

Stores events, documents (with summary text), and sources.

Stateful volume: postgres_data.

commons-worker (Python Scraper Node)

Role: The background engine.

Logic: Loops through all YAMLs in /configs.

Drivers:

civic_plus.py: HTML table parser.

aspnet.py: Playwright-based renderer for complex state.

rss.py: Universal fallback.

PDF Pipeline: Downloads PDFs -> pymupdf4llm -> Markdown -> DB.

commons-mcp (The Interface)

Role: Model Context Protocol Server.

Tools:

get_commons_calendar(start, end): Returns merged events from all sources.

search_commons_records(query): Full-text search of PDF summaries.

get_assistant_manifest(): Returns the bot name/persona to the LLM context.

commons-web (Public Web App)

Role: Citizen-facing web application.

Features:
- Event calendar with filtering by source/type
- Meeting minutes search and browse
- Upcoming meetings and agendas
- Mobile-responsive design

Tech: Next.js or similar (SSR for SEO, static where possible)

commons-admin (Admin Dashboard)

Role: Administrative interface for operators.

Features:
- Source health monitoring and status
- Manual scrape triggers
- View/edit configuration
- Error logs and diagnostics
- Data quality review

Tech: Next.js (can share component library with commons-web)

Auth: Protected, requires authentication

3. Directory Structure
Plaintext

/civic-commons
├── docker-compose.yml
├── /configs                 # Drop your city YAML here
│   └── twinsburg.yaml
├── /scraper                 # The Worker Service
│   ├── Dockerfile           # Includes Playwright browsers
│   ├── main.py              # Scheduler entrypoint
│   └── /drivers
│       ├── __init__.py
│       ├── base.py          # AbstractStrategy
│       ├── civic_plus.py
│       └── aspnet.py
├── /server                  # The MCP Service
│   ├── Dockerfile
│   ├── main.py              # FastMCP entrypoint
│   └── tools.py
├── /web                     # Public Web App
│   ├── Dockerfile
│   ├── package.json
│   └── /src
│       ├── /app             # Next.js app router
│       ├── /components      # Shared UI components
│       └── /lib             # API clients, utilities
├── /admin                   # Admin Dashboard
│   ├── Dockerfile
│   ├── package.json
│   └── /src
│       ├── /app
│       ├── /components
│       └── /lib
├── /shared                  # Shared code between web apps
│   ├── /ui                  # Shared component library (shadcn)
│   └── /db                  # Shared DB schema & queries
│       ├── schema.ts        # Drizzle schema definitions
│       ├── queries.ts       # Common query functions
│       └── index.ts         # Exports
└── /data                    # Database volume
4. Key Technologies
Orchestration: Docker Compose

Database: PostgreSQL 15
- Python services: asyncpg
- Web apps: Drizzle ORM (lightweight, SQL-like, type-safe)

ORM: Drizzle
- No binary/engine overhead (unlike Prisma)
- SQL-like syntax = LLM-friendly
- Full TypeScript inference from schema
- Shared schema in /shared/db

Browsing: Playwright (Python)

PDF Extraction: pymupdf4llm (Excellent for preserving layout/tables in Markdown)

Interface: MCP SDK (mcp)

Web Framework: Next.js (React, App Router, Server Components)

UI Components: shadcn/ui + Tailwind CSS + Radix UI (headless primitives)
- Components are copy-pasted into repo, not npm dependencies
- Lives in /shared/ui for cross-app reuse
- Explicit utility classes = LLM-friendly

Authentication: NextAuth.js (Auth.js) v5
- Self-hosted, no additional containers
- Sessions stored in PostgreSQL
- Credentials provider for dev, OAuth-ready for production
- Admin app protected, public web app open

DB Access Pattern: Direct via Server Components / Server Actions
- No separate API layer for simple CRUD
- Shared queries in /shared/db for reuse across web + admin

Deployment: Single Docker Compose stack (designed for future separation if needed)

5. Design Principles

A. Configuration is King
Every behavioral aspect of the system should be configurable via YAML—not hardcoded. This includes:
- Scrape schedules (cron expressions, intervals)
- Rate limiting / crawl delays per source
- Assistant name and persona
- Retry policies and timeout thresholds

If you're adding a feature and it's not configurable, ask yourself: "Should it be?"

B. Graceful Degradation & Local Cache
The system must be resilient to source failures. Design principles:
- **Last Known Good**: Always cache successful scrape results locally. If a source fails, serve stale data rather than nothing.
- **Error Handling**: Log failures, track consecutive failures per source, and surface health status via MCP tools.
- **Retry Logic**: Configurable exponential backoff per source type.

C. Deployment Model: Remote-First MCP
The MCP server will be deployed as a Docker container, potentially hosted on remote servers (not just localhost). This drives several design decisions:
- Authentication/authorization layer required for MCP endpoints
- Stateless MCP service (all state in PostgreSQL)
- Environment-based configuration for connection strings, secrets

6. Future Vision: Federated City Network

**Current Scope (v1):** Single city deployment with isolated stack and configurable data sources.

**Future Concept:** Cities don't exist in isolation. Regional decisions (county, school districts, park districts) often span multiple municipalities. The long-term vision is a federated model where:
- Each city runs its own Civic Commons stack
- Cities expose MCP interfaces that can be discovered and queried by neighboring deployments
- A "Regional Commons" could aggregate multiple city MCPs
- Example: "What are all school board meetings in Summit County this month?" queries multiple city endpoints

This is a **north star concept**—we will not implement federation in v1, but architecture decisions should not preclude it.

7. Development Standards (LLM-Optimized)

This project is built with LLM assistance. These standards maximize LLM effectiveness and code maintainability.

A. File Size & Structure
- **150-300 lines max per file** — Split larger files immediately
- **One concept per file** — A driver, a model, a utility—never mixed
- **Predictable naming** — `civic_plus.py` contains `CivicPlusDriver`, `event.py` contains `Event` model

B. Self-Documenting File Headers
Every Python file must start with a docstring:
```python
"""
Purpose: One-sentence description of what this file does
Dependencies: Key imports and why they're needed
Consumed by: What files/services use this module
Side effects: DB writes, file I/O, network calls (if any)
"""
```
This enables LLMs to understand file roles without full codebase context.

C. Type Hints & Explicitness
- **Type hints on all function signatures** — LLMs use these for reasoning
- **No magic** — Avoid metaclasses, complex decorators that hide behavior
- **Named parameters for calls with 2+ args** — `create_event(title="X", date=d)` not `create_event("X", d)`
- **Explicit imports** — `from models.event import Event` not `from models import *`

D. Interface-First Design
Define abstract base classes BEFORE implementations:
```python
# base.py defines the contract (small, stable)
class BaseDriver(ABC):
    @abstractmethod
    async def fetch_events(self) -> list[Event]: ...
```
Each implementation file only needs to know the interface, not sibling implementations.

E. Dependency Injection
Pass dependencies explicitly—never import singletons or global state:
```python
# Good — testable, explicit
async def scrape_source(db: Database, config: SourceConfig): ...

# Bad — hidden coupling
async def scrape_source(config: SourceConfig):
    from app import db  # 🚩 Hidden dependency
```

F. Configuration as Typed Schema
Use Pydantic models for all configuration:
```python
class SourceConfig(BaseModel):
    name: str
    driver: Literal["civic_plus", "rss", "aspnet"]
    schedule: str
    params: dict[str, Any]
```
Benefits: IDE autocomplete, runtime validation, LLM understands shape.

G. Test Structure
Tests mirror source structure 1:1:
```
/scraper/drivers/civic_plus.py  →  /tests/scraper/drivers/test_civic_plus.py
/server/tools.py                →  /tests/server/test_tools.py
```
Each test file stays focused and small.

H. Directory README Files
Complex directories get a README.md (10-20 lines max):
```markdown
# /drivers
Scrapers implementing `BaseDriver`. One file per source type.
To add a driver: copy `_template.py`, implement `fetch_events()`.
See `base.py` for the interface contract.
```

I. Git Practices
- **Atomic commits** — One logical change per commit
- **Descriptive messages** — "Add retry logic to CivicPlusDriver" not "updates"
- **Small PRs** — Easier for LLM to review and reason about

8. Resolved Design Decisions

Backend & Infrastructure:
- [x] ~~MCP Authentication~~ → **API Key in header (X-API-Key), env var config, stateless validation**
- [x] ~~Health checks~~ → **Docker healthcheck directives + /health endpoints per service (JSON status + timestamp)**
- [x] ~~Source health tracking~~ → **DB schema: last_success_at, last_failure_at, consecutive_failures, data_as_of**
- [x] ~~Rate limiting~~ → **Per-source config (delay_seconds, max_concurrent) with driver-type defaults**

Web Applications:
- [x] ~~UI component library~~ → **shadcn/ui + Tailwind CSS + Radix UI**
- [x] ~~Authentication provider~~ → **NextAuth.js v5 (self-hosted, PostgreSQL sessions)**
- [x] ~~Shared component strategy~~ → **/shared/ui directory, copy-paste pattern**
- [x] ~~API layer design~~ → **Drizzle ORM + Server Components/Actions (direct DB access)**
- [x] ~~SEO requirements~~ → **Basic SEO via Next.js defaults (SSR, metadata API, clean URLs). Admin is noindex.**
- [x] ~~Hosting strategy~~ → **Docker Compose (single stack, separable later)**

9. Database Schema (Core Tables)

```sql
-- Sources: Configuration + health tracking
CREATE TABLE sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,                    -- "City Council"
  driver TEXT NOT NULL,                  -- "civic_plus"
  config JSONB,                          -- driver params from YAML
  
  -- Health tracking
  last_success_at TIMESTAMPTZ,           -- Last successful scrape
  last_failure_at TIMESTAMPTZ,           -- Last failed scrape  
  consecutive_failures INT DEFAULT 0,
  last_error_message TEXT,
  
  -- Freshness
  data_as_of TIMESTAMPTZ,                -- When scraped data is current to
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Events: Meetings, hearings, etc.
CREATE TABLE events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id UUID REFERENCES sources(id),
  title TEXT NOT NULL,
  description TEXT,
  starts_at TIMESTAMPTZ NOT NULL,
  ends_at TIMESTAMPTZ,
  location TEXT,
  url TEXT,                              -- Link to original source
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Documents: PDFs, agendas, minutes
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id UUID REFERENCES sources(id),
  event_id UUID REFERENCES events(id),   -- Optional link to event
  title TEXT NOT NULL,
  doc_type TEXT,                         -- "agenda", "minutes", "packet"
  original_url TEXT,
  file_path TEXT,                        -- Local storage path
  content_markdown TEXT,                 -- Extracted text (pymupdf4llm)
  content_hash TEXT,                     -- For deduplication
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

10. Core Principles

**EDITORIAL NEUTRALITY**: This tool does nothing other than report details and aggregate information. It will NEVER be used to sway opinion. The platform presents facts, documents, and schedules—not endorsements, recommendations, or political positions. AI summaries must be factual and neutral.

11. Project Vision: The Community Forum

Civic Commons is not just a government meeting tracker—it's meant to be **the community forum**. Everything that makes Twinsburg a community belongs here:
- Government: City Council, School Board, Parks
- Civic: Library, Historical Society
- Community: Churches, Scouts, Youth Sports
- Business: Chamber, Local Businesses
- Regional: Metroparks, County resources

Members can submit new sites to monitor; administrators review and add sources.

12. Feature Roadmap

### v1 — Foundation (MVP)
Core infrastructure and basic functionality.

| Feature | Description | Status |
|---------|-------------|--------|
| Scraper Infrastructure | Worker service with driver pattern | Planned |
| MCP Server | LLM-accessible API | Planned |
| Public Web App | Calendar, search, basic browsing | Planned |
| Admin Dashboard | Health monitoring, manual triggers | Planned |
| Document Search | Full-text search with original + summary links | Planned |
| Source Health Tracking | Last success/failure, staleness indicators | Planned |
| Basic SEO | SSR, metadata, clean URLs | Planned |

### v1.1 — User Engagement
Features that bring users back.

| Feature | Description | Priority |
|---------|-------------|----------|
| **User Signup** | Optional registration for personalization. Site accessible without login. | High |
| **Email Newsletters** | Daily, weekly, monthly digest options | High |
| **Labels/Tags** | Events and topics tagged with categories, owner/decision-maker clear | High |
| **Calendar Export** | iCal/ICS feeds for Google Calendar, Apple Calendar | High |
| **Keyword Alerts** | Email/notification when specific terms appear | Medium |
| **Deadline View** | "What's due soon?" — Last day to vote, submit applications, etc. | Medium |

### v1.2 — Community Features
Interaction and engagement.

| Feature | Description | Priority |
|---------|-------------|----------|
| **Community Comments** | Residents can comment on topics/events | High |
| **Error Flagging** | Users can flag incorrect AI summaries | High |
| **"Dig Deeper" Feature** | Explore historical context on topics | Medium |
| **User Stories** | Residents can "tell their story" — community-voted context | Medium |
| **Timeline View** | Visual timeline of an issue across meetings | Medium |
| **Vote Tracking** | Who voted what and when on specific issues | Medium |

### v1.3 — Accessibility & Inclusion
Reaching everyone in the community.

| Feature | Description | Priority |
|---------|-------------|----------|
| **Accessibility (WCAG AA)** | Full compliance, screen readers, contrast, font sizes | Critical |
| **Senior Newsletter** | Larger print, emailed to distribution lists for printing/sharing | High |
| **Onboarding Flow** | "New to Twinsburg" vs "I know the basics" paths | Medium |
| **Print-Friendly Views** | Optimized for paper distribution | Medium |

### v1.4 — Civic Engagement
Deeper civic participation.

| Feature | Description | Priority |
|---------|-------------|----------|
| **Election/Vote Tracker** | What's on the next ballot? What are the issues? | High |
| **Public Records Integration** | How to tie into records requests | Medium |
| **Meeting Reminders** | "City Council meets tomorrow" notifications | Medium |

### v2.0 — Community Spotlight & Business
Expanding beyond government.

| Feature | Description | Priority |
|---------|-------------|----------|
| **Local Business Spotlight** | Periodic callouts to small businesses | Medium |
| **Chamber Integration** | Events, business news | Medium |
| **Community Source Submissions** | Members suggest new sources to monitor | Medium |
| **Church/Scout/Youth Events** | Broader community calendar | Medium |

### Future — Federation
| Feature | Description |
|---------|-------------|
| **Multi-City Deployment** | Regional queries across city boundaries |
| **Federated MCP Network** | Cities expose APIs to each other |

13. Technical Requirements (Non-Functional)

### Accessibility
- **WCAG AA Compliance** — Required for public web app
- Large text mode / high contrast mode
- Screen reader compatible
- Keyboard navigation

### Operations
- **Centralized Logging** — Structured logs, searchable, retained
- **Health Status Dashboard** — Real-time status of all services and sources
- **Comprehensive Documentation** — Ground-up docs for deployment, maintenance, contribution
- **.env.example** — All required secrets documented with example values

### Data Sync
- **Change Detection** — How to detect when source events are modified
- **Sync Strategy** — Full refresh vs. incremental updates
- **Conflict Resolution** — What happens when local data differs from source

14. Environment Configuration

Required secrets and configuration (create `.env` from `.env.example`):

```bash
# Database
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=civic_commons
POSTGRES_USER=commons
POSTGRES_PASSWORD=<generate-secure-password>

# MCP Server
MCP_API_KEY=<generate-secure-api-key>
MCP_PORT=8080

# Web Apps
NEXTAUTH_SECRET=<generate-secure-secret>
NEXTAUTH_URL=http://localhost:3000

# Admin credentials (dev only — use OAuth in production)
ADMIN_EMAIL=admin@localhost
ADMIN_PASSWORD=<secure-password>

# Optional: OAuth providers (production)
# GOOGLE_CLIENT_ID=
# GOOGLE_CLIENT_SECRET=

# Optional: Email (for newsletters/alerts)
# SMTP_HOST=
# SMTP_PORT=
# SMTP_USER=
# SMTP_PASSWORD=
# EMAIL_FROM=

# Optional: External services
# SENTRY_DSN=                    # Error tracking
# LOGFLARE_API_KEY=              # Log aggregation
```

15. Open Questions / TODO

### Architecture
- [ ] Define admin user roles (single admin vs. multi-user with permissions?)
- [ ] Backup strategy for PostgreSQL data
- [ ] Logging aggregation approach (stdout? file? Loki? external?)
- [ ] Change detection strategy for source sync

### Features (Need Design)
- [ ] How do community-voted "stories" work? Moderation?
- [ ] What triggers a "Dig Deeper" option? Manual curation or automatic?
- [ ] How to handle controversial topics neutrally?
- [ ] Business spotlight selection criteria — random? Nominated?
- [ ] Public records request integration — link out or actual integration?

### Content
- [ ] What community sources to include at launch?
- [ ] Who moderates community comments?
- [ ] Newsletter content curation — automated or manual?