# /web

The public-facing Next.js application for community residents.

## Overview

This is the main web application that residents use to access community information, search documents, and interact with the AI assistant.

## Tech Stack

- **Next.js 14** - App Router with Server Components
- **React 18** - UI library
- **TypeScript** - Type safety
- **Tailwind CSS** - Utility-first styling
- **shadcn/ui** - Component library (copy-paste)
- **Radix UI** - Headless primitives
- **NextAuth.js v5** - Authentication (optional login)
- **Drizzle ORM** - Database queries

## Directory Structure

```
/web
├── app/
│   ├── layout.tsx           # Root layout
│   ├── page.tsx             # Home page
│   ├── globals.css          # Global styles + Tailwind
│   ├── (public)/            # Public routes
│   │   ├── events/          # Events calendar
│   │   ├── documents/       # Document browser
│   │   └── search/          # Search results
│   └── api/                 # API routes
│       └── chat/            # AI chat endpoint
├── components/
│   ├── ui/                  # shadcn/ui components
│   └── features/            # Feature components
├── lib/
│   ├── db.ts               # Database client
│   └── utils.ts            # Utility functions
├── public/                  # Static assets
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

# Start production server
npm start
```

## Environment Variables

See `.env.example` in the project root for required variables.

## Features (v1)

- [ ] Home page with upcoming events
- [ ] Events calendar with filtering
- [ ] Document search and viewer
- [ ] AI chat assistant widget
- [ ] Source attribution
- [ ] Mobile-responsive design

## Docker

```bash
docker-compose up commons-web
```
