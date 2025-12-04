# run-dev.sh Improvements

## Summary
The `run-dev.sh` script has been enhanced to run cleanly from the project root with **zero manual configuration required**.

---

## 🎯 What Changed

### 1. ✅ Automatic .env Creation
**Backend** (`backend/.env`):
- Script now auto-creates minimal `.env` if missing
- Sets `DISABLE_STARTUP_INGESTION=true` by default (faster restarts)
- Warns if `OPENAI_API_KEY` is missing but still starts server
- Falls back to local embedding stubs (deterministic hash-based)

**Frontend** (`frontend/.env.local`):
- Script now auto-creates with ngrok URL: `https://will-node.ngrok.dev`
- Can be manually edited for local dev: `http://localhost:9000`

### 2. ✅ Fixed Container Command Bug
**Line 143**: Changed from hardcoded `podman` to `$CONTAINER_CMD`
- Now works correctly with both Docker and Podman
- Detects which container runtime is available
- Uses correct command for PostgreSQL health check

### 3. ✅ Removed --isolated Flag
**Line 153**: Removed `--isolated` from uvicorn command
- Allows proper virtual environment usage
- Ensures dependencies are found correctly

### 4. ✅ Enhanced .env.example
**Backend** (`backend/.env.example`):
- Comprehensive documentation of all config options
- Organized into logical sections
- Shows all new configuration parameters from `config.py`
- Example values for symbol/team configuration

**Frontend** (`frontend/.env.local.example`):
- New file documenting frontend configuration
- Shows ngrok URL setup
- Alternative configurations documented

---

## 🚀 Zero-Config Startup

You can now run from project root with **no setup**:

```bash
./run-dev.sh
```

### What Happens:
1. ✅ Detects Docker/Podman automatically
2. ✅ Starts PostgreSQL + pgvector container
3. ✅ Creates `backend/.env` if missing (warns about OpenAI key)
4. ✅ Syncs backend dependencies with `uv`
5. ✅ Backfills crypto prices on first run
6. ✅ Creates `frontend/.env.local` with ngrok URL
7. ✅ Installs frontend dependencies if needed
8. ✅ Starts all services

### Services Available:
- **Frontend**: http://localhost:3000
- **Backend**: http://localhost:9000
- **Database**: postgresql://localhost:5433
- **Adminer**: http://localhost:8080

### Frontend Access:
- Frontend connects to backend via ngrok: `https://will-node.ngrok.dev`
- This allows external access and testing from any device

---

## ⚙️ Configuration Options

### Quick Start (No OpenAI Key)
```bash
# Just run it - uses local embedding stubs
./run-dev.sh
```

**What works without OpenAI key:**
- ✅ Backend starts successfully
- ✅ Frontend loads
- ✅ Database queries work
- ✅ Crypto price backfill works
- ⚠️ Embeddings use local hash-based stubs (deterministic but not semantic)

**What requires OpenAI key:**
- ❌ Semantic event search (uses stub vectors instead)
- ❌ Event-based forecasting (needs real embeddings)
- ❌ RSS ingestion with real embeddings

### Add OpenAI Key Later
```bash
# Edit backend/.env
nano backend/.env

# Add your key:
OPENAI_API_KEY=sk-proj-...

# Restart backend (Ctrl+C then ./run-dev.sh)
```

### Skip Ingestion (Faster Restarts)
Already configured by default in auto-generated `.env`:
```bash
DISABLE_STARTUP_INGESTION=true
```

To run ingestion manually:
```bash
cd backend
uv run python -m ingest.rss_ingest
uv run python -m ingest.backfill_crypto_returns
```

### Change Backend URL (Frontend)
Edit `frontend/.env.local`:
```bash
# For local development
NEXT_PUBLIC_API_URL=http://localhost:9000

# For ngrok tunnel (default)
NEXT_PUBLIC_API_URL=https://will-node.ngrok.dev

# For production
NEXT_PUBLIC_API_URL=https://api.yourapp.com
```

---

## 🛠️ Troubleshooting

### "PostgreSQL failed to start within 30 seconds"
```bash
# Check container status
docker ps -a  # or: podman ps -a

# View logs
docker logs semantic_db  # or: podman logs semantic_db

# Full reset
docker compose down -v
./run-dev.sh
```

### "Backend failed to start"
```bash
# Check for port conflicts
lsof -i :9000

# View backend logs
cd backend
uv run uvicorn app:app --reload --host 127.0.0.1 --port 9000
```

### "Frontend failed to start"
```bash
# Check for port conflicts
lsof -i :3000

# Clean install
cd frontend
rm -rf node_modules .next
npm install
npm run dev
```

### "Connection refused" errors in frontend
Check `frontend/.env.local`:
- Ensure `NEXT_PUBLIC_API_URL` is correct
- For ngrok: verify tunnel is running (`ngrok http 9000`)
- For local: use `http://localhost:9000`

---

## 📊 First Run vs. Subsequent Runs

### First Run (Fresh Database)
```
[dev] Starting database container...
[dev] Waiting for PostgreSQL to be ready...
[dev] PostgreSQL is ready!
[dev] Creating backend/.env...
[dev] ⚠️  OPENAI_API_KEY not configured
[dev] Syncing backend dependencies...
[dev] Backfilling crypto prices (first run)...
[backfill] Fetching BTC-USD...
[backfill] Inserted ~365 rows for BTC-USD
[dev] Creating frontend/.env.local with ngrok URL
[dev] Installing frontend dependencies...
```

### Subsequent Runs (Database Exists)
```
[dev] Database container already running
[dev] Syncing backend dependencies...
[dev] Crypto prices already loaded (1095 rows)
[dev] Backend running at http://localhost:9000
[dev] Frontend running at http://localhost:3000
```

**Much faster!** Skips crypto backfill and dependency installs.

---

## 🔧 Advanced Configuration

### Add More Crypto Symbols
Edit `backend/.env`:
```bash
CRYPTO_SYMBOLS=BTC-USD:BTC-USD,ETH-USD:ETH-USD,SOL-USD:SOL-USD,AVAX-USD:AVAX-USD
```

### Change Scheduler Intervals
Edit `backend/.env`:
```bash
RSS_INGEST_INTERVAL_HOURS=2      # Every 2 hours
CRYPTO_BACKFILL_INTERVAL_HOURS=6  # 4x daily
```

### Adjust API Limits
Edit `backend/.env`:
```bash
API_MAX_EVENTS_LIMIT=500          # Allow up to 500 events per query
MIN_HORIZON_MINUTES=15            # Allow 15-minute forecasts
MAX_HORIZON_MINUTES=86400         # Allow 60-day forecasts
```

---

## 🎯 Recommended Workflow

### Development (No API Costs)
```bash
# 1. Start without OpenAI key (uses local stubs)
./run-dev.sh

# 2. Develop features, test UI, work on models
# 3. When ready to test embeddings:
#    Add OPENAI_API_KEY to backend/.env
#    Restart with Ctrl+C then ./run-dev.sh
```

### Testing Ingestion
```bash
# Start server with ingestion disabled (default)
./run-dev.sh

# In another terminal, run ingestion manually
cd backend
uv run python -m ingest.rss_ingest
uv run python -m ingest.backfill_crypto_returns
```

### Production Setup
```bash
# 1. Copy .env.example files
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local

# 2. Add real API keys
nano backend/.env  # Add OPENAI_API_KEY

# 3. Configure for production
nano backend/.env  # Set DISABLE_STARTUP_INGESTION=false
nano frontend/.env.local  # Set production API URL

# 4. Deploy
```

---

## ✅ Testing Checklist

Before committing changes:

- [ ] Run `./run-dev.sh` from clean state (no .env files)
- [ ] Verify backend starts with warning about OpenAI key
- [ ] Verify frontend starts with ngrok URL
- [ ] Check http://localhost:3000 loads
- [ ] Check http://localhost:9000/health returns 200
- [ ] Stop with Ctrl+C and verify clean shutdown
- [ ] Run again to verify fast subsequent startup

---

## 📝 Files Modified

### Scripts
- `run-dev.sh` - Enhanced auto-configuration

### Configuration
- `backend/.env.example` - Comprehensive documentation (93 lines)
- `frontend/.env.local.example` - NEW frontend config template

### Auto-Created (by script)
- `backend/.env` - Minimal config with warnings
- `frontend/.env.local` - Ngrok URL configuration

---

## 🎉 Summary

The `run-dev.sh` script now provides a **true zero-config experience**:

✅ No manual .env setup required
✅ Works with Docker or Podman
✅ Automatically configures ngrok URL
✅ Warns about missing API keys but still works
✅ Fast subsequent startups
✅ Comprehensive .env.example for reference

Just run `./run-dev.sh` and start coding! 🚀
