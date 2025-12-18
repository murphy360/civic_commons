# /shared

Shared TypeScript code used across web and admin applications.

## Overview

This directory contains shared TypeScript code that is used by both the `/web` and `/admin` Next.js applications. It includes database schemas, types, and reusable utilities.

## Structure

```
/shared
├── db/
│   ├── index.ts             # Drizzle client export
│   └── schema.ts            # All table schemas
├── types/
│   ├── index.ts             # Re-exports
│   ├── event.ts             # Event types
│   ├── document.ts          # Document types
│   └── source.ts            # Source types
└── package.json
```

## Database Schema

Uses Drizzle ORM with PostgreSQL. Key tables:

| Table | Description |
|-------|-------------|
| `sources` | Data source definitions |
| `events` | Calendar events |
| `documents` | Indexed documents (agendas, minutes, etc.) |
| `event_sources` | Event-source relationships |
| `event_documents` | Event-document relationships |
| `legislation_mentions` | Tracked legislation items |
| `newsletters` | Generated newsletters |

## Usage

```typescript
// In web or admin
import { db } from '@/shared/db';
import { events, documents, sources } from '@/shared/db/schema';
import type { Event, Document } from '@/shared/types';
```

## Adding Schema Changes

1. Edit `db/schema.ts`
2. Add migration in `scripts/migrations/`
3. Apply migration:
```bash
docker compose exec db psql -U commons -d civic_commons -f /scripts/migrations/NNN_name.sql
```
