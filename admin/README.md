# /admin

The internal admin dashboard for managing Civic Commons data sources and monitoring system health.

**Container:** `civic_commons_admin` | **Port:** 3001

## Overview

This is the internal admin interface for city staff and system administrators to manage sources, trigger scrapes, view logs, and monitor the data pipeline.

## Tech Stack

- **Next.js 14** - App Router with Server Components
- **React 18** - UI library
- **TypeScript** - Type safety
- **Tailwind CSS** - Utility-first styling
- **shadcn/ui** - Component library
- **Drizzle ORM** - Database queries

## Directory Structure

```
/admin
├── app/
│   ├── layout.tsx           # Root layout
│   ├── page.tsx             # Dashboard home
│   ├── globals.css          # Global styles
│   ├── sources/             # Source management
│   ├── queue/               # Queue monitoring
│   ├── logs/                # Activity logs viewer
│   ├── legislation/         # Legislation management
│   ├── components/          # Dashboard components
│   └── api/                 # API routes
├── lib/
│   └── utils.ts            # Utility functions
└── next.config.js
```

## Key Features

- **Source Management** - View and configure data sources
- **Manual Scrape Triggers** - Click to trigger immediate scrape
- **Queue Monitoring** - View download, extraction, AI queue status
- **Activity Logs** - Real-time view of system activities
- **Health Monitoring** - See last scrape time and status
- **Document Stats** - View document counts per source

## Pages

| Route | Purpose |
|-------|---------|
| `/` | Dashboard overview |
| `/sources` | Source configuration |
| `/queue` | Queue status and management |
| `/logs` | Activity log viewer |
| `/legislation` | Legislation tracking |

## Development

```bash
# Install dependencies
npm install

# Run development server (port 3001)
npm run dev

# Build for production
npm run build
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `NEXTAUTH_SECRET` | NextAuth session secret |

## Docker

```bash
docker compose up commons-admin
# Access at http://localhost:3001
```

## Triggering Scrapes

The admin dashboard allows manual scrape triggers:
1. Click the "Trigger Scrape" button for a source
2. Sets `manual_scrape_trigger = true` in database
3. Worker picks up the trigger within 15 seconds
4. Status updates automatically
