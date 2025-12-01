# Quick Start Guide

Get the BloombergGPT Semantic Markets backend running in under 5 minutes.

## Prerequisites

- Docker or Podman
- Node.js 20+ (for frontend)
- Python 3.11+ (auto-managed by uv)
- OpenAI API key

## 1. Clone & Setup

```bash
git clone <your-repo-url>
cd bloombergGPT
```

## 2. Configure Environment

Create `backend/.env`:

```bash
# Required
OPENAI_API_KEY=sk-...

# Optional - Development mode (recommended)
DISABLE_STARTUP_INGESTION=true
```

**Pro tip:** Use `DISABLE_STARTUP_INGESTION=true` to skip ingestion on every restart. Saves time and API costs during development.

## 3. Start Everything

```bash
./run-dev.sh
```

This will:
1. Start PostgreSQL + pgvector
2. Install backend dependencies (via uv)
3. Backfill crypto prices (first run only)
4. Start FastAPI backend
5. Install frontend dependencies
6. Start Next.js frontend

## 4. Access Services

- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:9000
- **API Docs:** http://localhost:9000/docs
- **Database:** postgresql://semantic:semantic@localhost:5433/semantic_markets
- **Adminer:** http://localhost:8080

## 5. Manual Ingestion (Optional)

If you disabled startup ingestion, run this when you want fresh data:

```bash
cd backend
uv run python -m ingest.rss_ingest
```

First run will fetch everything. Subsequent runs are smart (only new entries).

## 6. Verify It Works

Test the API:

```bash
# Health check
curl http://localhost:9000/health

# Recent events
curl http://localhost:9000/events/recent?limit=5

# Asset forecast
curl "http://localhost:9000/forecast/asset?symbol=BTC-USD&horizon_minutes=1440"
```

## Common Operations

### Add More RSS Sources

Edit `backend/ingest/rss_ingest.py`:

```python
RSS_FEEDS: Dict[str, str] = {
    "wired_ai": "https://www.wired.com/feed/tag/ai/latest/rss",
    "your_source": "https://your-rss-feed.com/rss",  # Add this
}
```

### Reset Database

```bash
docker compose down -v
docker compose up -d db
./run-dev.sh
```

### Run Tests

```bash
cd backend
uv run pytest
```

### Check Ingestion Status

```bash
psql postgresql://semantic:semantic@localhost:5433/semantic_markets -c "SELECT * FROM feed_metadata;"
```

### View Logs

Backend logs are in the terminal where you ran `./run-dev.sh`.

## Development Workflow

### Fast Iteration (Recommended)

1. Set `DISABLE_STARTUP_INGESTION=true` in `backend/.env`
2. Start once: `./run-dev.sh`
3. Make code changes (auto-reloads)
4. Run ingestion manually when needed

### Backend Only

```bash
cd backend
uv sync
uv run uvicorn app:app --reload --host 127.0.0.1 --port 9000
```

### Frontend Only

```bash
cd frontend
npm run dev
```

## Troubleshooting

### "Connection refused" to database
```bash
docker compose up -d db
# Wait 10 seconds for postgres to start
```

### "Table does not exist"
```bash
# Database needs initialization
docker compose down -v
docker compose up -d db
```

### "OPENAI_API_KEY not found"
```bash
# Create backend/.env with your API key
echo "OPENAI_API_KEY=sk-..." > backend/.env
```

### Backend startup is slow
```bash
# Enable development mode
echo "DISABLE_STARTUP_INGESTION=true" >> backend/.env
```

### Want fresh data but ingestion is disabled
```bash
cd backend
uv run python -m ingest.rss_ingest
```

## Performance Tips

1. **Use DISABLE_STARTUP_INGESTION=true** during development
2. **Don't reset database** unless necessary (loses data)
3. **Ingestion is smart** - subsequent runs are 30-60x faster
4. **Close Adminer** when not using (saves memory)

## Next Steps

- Read `CLAUDE.md` for complete documentation
- Check `docs/ROADMAP.md` for feature plans
- See `OPTIMIZATIONS.md` for technical deep dive
- Explore API at http://localhost:9000/docs

## Need Help?

- **API Reference:** http://localhost:9000/docs (when running)
- **Documentation:** `CLAUDE.md`
- **Architecture:** `docs/FORECASTGPT_MASTER_PLAN.md`
- **Changes Log:** `CHANGES.md`

---

**You're ready to build! 🚀**

The system is optimized for cost-efficiency and fast iteration. Have fun!
