# /admin

The internal admin dashboard for managing Civic Commons.

## Overview

This is the internal admin interface for city staff and system administrators to manage sources, monitor scraper health, and configure community settings.

## Tech Stack

- **Next.js 14** - App Router with Server Components
- **React 18** - UI library
- **TypeScript** - Type safety
- **Tailwind CSS** - Utility-first styling
- **shadcn/ui** - Component library
- **NextAuth.js v5** - Authentication (required)
- **Drizzle ORM** - Database queries

## Directory Structure

```
/admin
├── app/
│   ├── layout.tsx           # Root layout with auth
│   ├── page.tsx             # Dashboard home
│   ├── globals.css          # Global styles
│   ├── (auth)/              # Auth routes
│   │   ├── login/           # Login page
│   │   └── logout/          # Logout handler
│   ├── (dashboard)/         # Protected routes
│   │   ├── sources/         # Source management
│   │   ├── cities/          # City configuration
│   │   ├── logs/            # Scraper logs
│   │   └── settings/        # System settings
│   └── api/                 # API routes
│       └── auth/            # NextAuth handlers
├── components/
│   ├── ui/                  # shadcn/ui components
│   └── dashboard/           # Dashboard components
├── lib/
│   ├── auth.ts             # Auth configuration
│   ├── db.ts               # Database client
│   └── utils.ts            # Utility functions
├── next.config.js
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

## Development

```bash
# Install dependencies
npm install

# Run development server
npm run dev

# Build for production
npm run build
```

## Authentication

Admin access requires NextAuth.js authentication. Supported providers:
- GitHub OAuth (for development)
- Email/Password (for production)

## Features (v1)

- [ ] Dashboard with system health overview
- [ ] Source management (enable/disable, add new)
- [ ] City configuration editor
- [ ] Scraper log viewer
- [ ] Manual scrape trigger
- [ ] User management (admin users)

## Docker

```bash
docker-compose up commons-admin
```
