# Civic Commons - Quick Start Guide

Get up and running in under 5 minutes with Docker. **No local Node.js or Python installation required.**

## Prerequisites

- **Docker Desktop** - [Download](https://www.docker.com/products/docker-desktop/)

That's it! Everything runs in containers.

## 1. Setup Environment

```powershell
# From project root
Copy-Item .env.example .env
```

Edit `.env` and set these required values:

```dotenv
# Pick a secure password
POSTGRES_PASSWORD=your_secure_password_here

# Generate random secrets (or use any random string)
MCP_API_KEY=your_random_api_key_here
NEXTAUTH_SECRET=your_random_secret_here

# Ports (change if 3002/3003 are in use)
WEB_PORT=3002
ADMIN_PORT=3003
```

> **Tip:** On Windows, you can generate random strings with PowerShell:
> ```powershell
> -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 32 | ForEach-Object {[char]$_})
> ```

## 2. Start Everything

```powershell
docker compose up -d
```

That's it! Docker will:
- Build all service images
- Start PostgreSQL and auto-initialize the database schema
- Seed Twinsburg, OH as the default city with 6 data sources
- Start the web app, admin dashboard, and scraper worker

First run takes 2-3 minutes to build images. Subsequent starts are instant.

## 3. Access the Apps

| Service | URL | Description |
|---------|-----|-------------|
| Web App | http://localhost:3002 | Public-facing site |
| Admin | http://localhost:3003 | Admin dashboard |
| MCP Server | http://localhost:8080 | LLM API (on-demand) |
| Database | localhost:5432 | PostgreSQL |

## 4. Verify Everything Works

```powershell
# Check all containers are running
docker compose ps

# Test web health endpoint
Invoke-RestMethod http://localhost:3002/api/health

# Test admin health endpoint
Invoke-RestMethod http://localhost:3003/api/health

# View scraper logs
docker compose logs -f commons-worker
```

You should see:
- `status: healthy` from both health endpoints
- Worker logs showing 6 scheduled jobs for Twinsburg

## Common Issues

### Port already in use
Edit `.env` and change the ports:
```dotenv
WEB_PORT=3004
ADMIN_PORT=3005
DB_PORT=5433
```
Then restart: `docker compose down && docker compose up -d`

### Database connection failed
```powershell
# Check database health
docker compose logs db

# Verify tables were created
docker exec civic_commons_db psql -U commons -d civic_commons -c "\dt"
```

### Need to reset the database
```powershell
# WARNING: This deletes all data
docker compose down -v
docker compose up -d
```

### Images need rebuilding after code changes
```powershell
docker compose build --no-cache
docker compose up -d
```

## Stopping Services

```powershell
# Stop all (keeps data)
docker compose down

# Stop and remove volumes (WARNING: deletes data)
docker compose down -v
```

## Development Mode (Optional)

For active development with hot reload, you can run services locally:

```powershell
# Terminal 1: Database only in Docker
docker compose up db

# Terminal 2: Run web locally (requires Node.js 20+)
cd web
npm install
npm run dev

# Terminal 3: Run scraper locally (requires Python 3.12+)
cd scraper
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Next Steps

- 📖 Read `PROJECT_CONTEXT.md` for architecture details
- 🏙️ Edit `configs/twinsburg.yaml` to customize data sources
- 👤 Review personas in `personas/` directory
- 🔧 Configure additional cities by creating new YAML files
