# Local Development Guide

## Overview

Your local development environment is now **manual start** (does not auto-start on boot). This saves resources and avoids confusion with the production environment.

**Production**: http://maybe.probablyfine.lol (auto-deploys on `git push`)
**Local**: http://localhost:9000 (manual start when needed)

## Starting Local Development

### Option 1: Full Stack (Recommended)

Start everything with one command:

```bash
cd /Users/will/Programming/Projects/bloombergGPT
./run-dev.sh
```

This starts:
- PostgreSQL database (Docker on port 5433)
- Backend API (uvicorn on port 9000)
- Frontend (Next.js on port 3000)

Access at:
- Backend: http://localhost:9000/health
- Frontend: http://localhost:3000

### Option 2: Backend Only

If you only need the backend:

```bash
cd /Users/will/Programming/Projects/bloombergGPT/backend

# Start database
docker compose up -d db

# Start backend
uv run uvicorn app:app --reload --host 127.0.0.1 --port 9000
```

### Option 3: Frontend Only

If backend is already running on production:

```bash
cd /Users/will/Programming/Projects/bloombergGPT/frontend

# Point to production backend
export NEXT_PUBLIC_API_URL=http://maybe.probablyfine.lol

# Start frontend
npm run dev
```

## Stopping Local Services

### Stop Backend
```bash
# If started with run-dev.sh, just Ctrl+C in the terminal

# Or kill the process
pkill -f "uvicorn app:app"
```

### Stop Database
```bash
cd /Users/will/Programming/Projects/bloombergGPT/backend
docker compose down
```

### Stop Frontend
```bash
# Ctrl+C in the terminal where npm is running
```

## Development Workflow

### For Quick Changes
1. Make changes to code
2. Backend auto-reloads (if using `--reload` flag)
3. Frontend auto-reloads (if using `npm run dev`)
4. Test locally
5. Commit and push to auto-deploy to production

### For Production Testing
1. Make changes
2. Commit and push to GitHub
3. Wait ~50 seconds for auto-deployment
4. Test at http://maybe.probablyfine.lol

## Checking What's Running

```bash
# Check LaunchAgents (should be empty now)
launchctl list | grep bloomberg

# Check backend process
ps aux | grep uvicorn

# Check database container
docker ps | grep postgres

# Check frontend process
ps aux | grep "next dev"
```

## Re-enabling Auto-Start (If Needed)

If you want local services to auto-start on login again:

```bash
# Load backend LaunchAgent
launchctl load ~/Library/LaunchAgents/com.bloomberggpt.backend.plist

# Load database LaunchAgent
launchctl load ~/Library/LaunchAgents/com.bloomberggpt.database.plist
```

To disable again:
```bash
launchctl unload ~/Library/LaunchAgents/com.bloomberggpt.backend.plist
launchctl unload ~/Library/LaunchAgents/com.bloomberggpt.database.plist
```

## Environment Variables

Your local `.env` files are separate from production:

**Backend**: `/Users/will/Programming/Projects/bloombergGPT/backend/.env`
- OpenAI API key
- Weaviate credentials
- NFL News API key
- Feature flags (DISABLE_STARTUP_INGESTION, etc.)

**Frontend**: `/Users/will/Programming/Projects/bloombergGPT/frontend/.env.local`
- NEXT_PUBLIC_API_URL (defaults to http://localhost:9000)

Production `.env` files are on the Oracle server at `/opt/bloomberggpt/.env`

## Common Tasks

### Run Tests
```bash
cd backend
uv run pytest
```

### Database Operations
```bash
cd backend

# Connect to local database
uv run psql $DATABASE_URL

# Run migrations (if any)
# Migration commands here...

# Backup local database
docker exec semantic_markets_db pg_dump -U semantic semantic_markets > backup.sql
```

### Manual Ingestion (Skip Auto-Scheduled Jobs)
```bash
cd backend

# Ingest RSS feeds
uv run python -m ingest.rss_ingest

# Ingest NFL news
uv run python -m ingest.nfl_news_api

# Backfill crypto prices
uv run python -m ingest.backfill_crypto_returns
```

## Logs

### Backend Logs
If you started with LaunchAgent (and loaded it):
```bash
tail -f /Users/will/Programming/Projects/bloombergGPT/logs/backend-stdout.log
```

If started manually:
- Logs appear in your terminal

### Frontend Logs
- Logs appear in your terminal where you ran `npm run dev`

### Database Logs
```bash
docker logs -f semantic_markets_db
```

## Troubleshooting

### Port Already in Use
```bash
# Kill process on port 9000 (backend)
lsof -ti:9000 | xargs kill -9

# Kill process on port 3000 (frontend)
lsof -ti:3000 | xargs kill -9

# Kill process on port 5433 (database)
docker compose down
```

### Database Connection Errors
```bash
# Check if database is running
docker ps | grep postgres

# Restart database
cd backend
docker compose restart db

# Check logs
docker logs semantic_markets_db
```

### "Module not found" errors
```bash
cd backend
uv sync  # Reinstall dependencies
```

## Summary

- **Local**: Manual start (use `./run-dev.sh`)
- **Production**: Auto-deploys on `git push`
- **No auto-start**: Saves resources when not developing
- **LaunchAgents**: Still available but unloaded (can re-enable if needed)
