# /shared

Shared code used across multiple services.

## Overview

This directory contains shared TypeScript code that is used by both the `/web` and `/admin` Next.js applications. It includes database schemas, types, and reusable utilities.

## Structure

```
/shared
├── db/
│   ├── index.ts             # Drizzle client export
│   ├── schema.ts            # All table schemas
│   └── migrations/          # Generated migrations
├── types/
│   ├── index.ts             # Re-exports
│   ├── event.ts             # Event types
│   ├── document.ts          # Document types
│   └── source.ts            # Source types
└── ui/                      # Shared UI components (future)
```

## Database Schema

Uses Drizzle ORM with PostgreSQL. Tables:

- `cities` - City configurations
- `sources` - Data source definitions
- `events` - Calendar events
- `documents` - Indexed documents
- `users` - Admin users (NextAuth)
- `accounts` - OAuth accounts (NextAuth)
- `sessions` - User sessions (NextAuth)

## Usage

```typescript
// In web or admin
import { db } from '@/shared/db';
import { events, documents } from '@/shared/db/schema';
import type { Event, Document } from '@/shared/types';
```

## Migrations

```bash
# Generate migration after schema changes
cd shared
npx drizzle-kit generate:pg

# Push schema to database (development)
npx drizzle-kit push:pg
```
