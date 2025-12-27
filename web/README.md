# /web

The public-facing Next.js application for community residents.

**Container:** `civic_commons_web` | **Port:** 3000

## Overview

This is the main web application that residents use to browse community events, search documents, watch meeting videos, and interact with AI-powered features.

## Tech Stack

- **Next.js 14** - App Router with Server Components
- **React 18** - UI library
- **TypeScript** - Type safety
- **Tailwind CSS** - Utility-first styling
- **shadcn/ui** - Component library
- **Drizzle ORM** - Database queries

## Directory Structure

```
/web
├── app/
│   ├── layout.tsx           # Root layout with Header
│   ├── page.tsx             # Home page
│   ├── globals.css          # Global styles + Tailwind
│   ├── events/              # Events calendar & details
│   ├── documents/           # Document browser & viewer
│   │   └── [id]/            # Document detail page
│   ├── videos/              # Meeting video browser
│   ├── legislation/         # Legislation tracking
│   ├── newsletters/         # Generated newsletters
│   ├── discuss/             # AI chat interface
│   ├── actions/             # Server actions
│   │   └── documents.ts     # Reprocess, prioritize actions
│   ├── components/          # Shared components
│   │   ├── Header.tsx       # Navigation header
│   │   ├── AISummaryBadge.tsx   # AI summary status
│   │   └── LinkStatusBadge.tsx  # Document link status
│   └── api/                 # API routes
│       └── chat/            # AI chat endpoint
├── lib/
│   ├── db.ts               # Database client
│   └── utils.ts            # Utility functions
├── public/                  # Static assets
└── next.config.js
```

## Key Features

- **Events Calendar** - Browse upcoming and past civic events
- **Document Search** - Full-text search across agendas, minutes, packets
- **AI Summaries** - View AI-generated summaries of documents
- **Meeting Videos** - Watch YouTube recordings of meetings
- **Legislation Tracking** - Track ordinances and resolutions
- **Newsletters** - Read auto-generated community digests
- **AI Chat** - Ask questions about civic data (calls API server)

## Development

```bash
# Install dependencies
npm install

# Run development server (port 3000)
npm run dev

# Build for production
npm run build
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `NEXT_PUBLIC_API_URL` | API server URL (for chat) |
| `NEXTAUTH_SECRET` | NextAuth session secret |
| `DOCUMENT_STORAGE_DIR` | Path to PDF storage |

## Docker

```bash
docker compose up commons-web
# Access at http://localhost:3002
```
