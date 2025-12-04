# Testing Guide for run-dev.sh

## Quick Test Steps

### Test 1: Clean Start (No Existing .env Files)

```bash
# 1. Remove any existing .env files
rm -f backend/.env frontend/.env.local

# 2. Run the script
./run-dev.sh

# Expected output:
# - Creates backend/.env
# - Warns about missing OPENAI_API_KEY
# - Creates frontend/.env.local with ngrok URL
# - Starts all services
# - Shows all 4 URLs
# - Says "Press Ctrl+C to stop"
```

**✓ Pass if**: All services start, you see the URLs, no errors

### Test 2: Ctrl+C Clean Shutdown

```bash
# With run-dev.sh running, press Ctrl+C

# Expected output:
# [dev] Shutting down...
# [dev] Stopping backend (PID: XXXXX)...
# [dev] Stopping frontend (PID: XXXXX)...
# [dev] Stopped all processes. Database container still running.
# [dev] To stop database: docker compose down

# Then verify processes are gone:
ps aux | grep uvicorn    # Should be empty
ps aux | grep next       # Should be empty
```

**✓ Pass if**:
- Script exits immediately
- No "Restarting..." messages
- No zombie processes remain
- Returns to shell prompt

### Test 3: Subsequent Run (Faster Startup)

```bash
# Run again after stopping
./run-dev.sh

# Expected output:
# - Skips .env creation
# - Skips crypto backfill (already loaded)
# - Skips npm install (already done)
# - Starts much faster (~5 seconds)
```

**✓ Pass if**: Starts in under 10 seconds, no downloads

### Test 4: Container Runtime Detection

```bash
# Check which runtime you have
which docker && echo "Has Docker"
which podman && echo "Has Podman"

# Run script
./run-dev.sh

# Expected output:
# [dev] Using container runtime: docker  (or podman)
```

**✓ Pass if**: Correctly detects your container runtime

---

## Detailed Verification

### Verify Backend Started Correctly

```bash
# In another terminal while run-dev.sh is running:

# 1. Check health endpoint
curl http://localhost:9000/health
# Expected: {"status":"healthy","database":"ok","pgvector":"ok"}

# 2. Check new configuration endpoints
curl http://localhost:9000/symbols/available
# Expected: {"all":["BTC-USD","ETH-USD","XMR-USD","NVDA"],"crypto":[...],"equity":[...]}

curl http://localhost:9000/horizons/available
# Expected: [{"value":1440,"label":"24 hours","available":true}]

curl http://localhost:9000/sources/available
# Expected: [{"value":"coindesk","label":"Coindesk","count":...},...]
```

### Verify Frontend Started Correctly

```bash
# 1. Open browser
open http://localhost:3000

# 2. Check if it loads
# Expected: ForecastGPT dashboard loads

# 3. Check if it connects to backend via ngrok
# Open browser console (F12)
# Expected: API calls to https://will-node.ngrok.dev
```

### Verify Environment Files Created

```bash
# Check backend/.env
cat backend/.env
# Expected:
# DISABLE_STARTUP_INGESTION=true
# # OPENAI_API_KEY=sk-...

# Check frontend/.env.local
cat frontend/.env.local
# Expected:
# NEXT_PUBLIC_API_URL=https://will-node.ngrok.dev
```

---

## Edge Case Tests

### Test 5: Kill Backend Manually

```bash
# With script running, find backend PID:
ps aux | grep uvicorn

# Kill it:
kill -9 <backend_pid>

# Expected output from script:
# [dev] Backend process died unexpectedly
# [dev] Shutting down...
# (cleanup runs)
```

**✓ Pass if**: Script detects death and cleanly exits

### Test 6: Kill Frontend Manually

```bash
# With script running, find frontend PID:
ps aux | grep next

# Kill it:
kill -9 <frontend_pid>

# Expected output from script:
# [dev] Frontend process died unexpectedly
# [dev] Shutting down...
# (cleanup runs)
```

**✓ Pass if**: Script detects death and cleanly exits

### Test 7: Database Not Running

```bash
# Stop database first
docker compose down  # or: podman-compose down

# Run script
./run-dev.sh

# Expected output:
# [dev] Starting database container...
# [dev] Waiting for PostgreSQL to be ready...
# [dev] PostgreSQL is ready!
```

**✓ Pass if**: Script starts database automatically

### Test 8: Port Already in Use

```bash
# Start something on port 9000
python3 -m http.server 9000 &

# Run script
./run-dev.sh

# Expected output:
# [dev] Backend failed to start
# (cleanup runs)
```

**✓ Pass if**: Script exits gracefully with error message

---

## Performance Tests

### Test 9: First Run Timing

```bash
# Clean slate
rm -rf backend/.env frontend/.env.local backend/.venv frontend/node_modules

# Time it
time ./run-dev.sh
# (Press Ctrl+C after services start)

# Expected: 30-120 seconds (depends on internet speed)
```

### Test 10: Subsequent Run Timing

```bash
# With everything already set up
time ./run-dev.sh
# (Press Ctrl+C after services start)

# Expected: 5-10 seconds
```

---

## Troubleshooting Scenarios

### Scenario 1: Script Won't Stop

**Symptoms**: Ctrl+C pressed but script keeps running

**Debug**:
```bash
# Check if trap is working
trap -p INT TERM

# Check PIDs
echo $BACKEND_PID
echo $FRONTEND_PID

# Manual kill
kill -9 $BACKEND_PID $FRONTEND_PID

# Nuclear option
pkill -9 uvicorn
pkill -9 node
```

### Scenario 2: Processes Restart After Ctrl+C

**Symptoms**: Services keep restarting even after cleanup

**Debug**:
```bash
# Check for orphaned processes
ps aux | grep uvicorn | grep -v grep
ps aux | grep next | grep -v grep

# Check if systemd/launchd is restarting them
systemctl status uvicorn  # Linux
launchctl list | grep uvicorn  # macOS

# Kill all Python/Node processes (careful!)
pkill -9 python3
pkill -9 node
```

### Scenario 3: Database Connection Refused

**Symptoms**: Backend starts but can't connect to DB

**Debug**:
```bash
# Check if container is running
docker ps  # or: podman ps

# Check if PostgreSQL is ready
docker exec semantic_db pg_isready -U semantic

# Check logs
docker logs semantic_db

# Verify port is correct
docker port semantic_db 5432
# Expected: 0.0.0.0:5433
```

---

## Success Criteria Checklist

After running all tests, you should have:

- [ ] Script starts cleanly without errors
- [ ] All 4 services show as running
- [ ] Ctrl+C stops immediately (no restarts)
- [ ] No zombie processes after stopping
- [ ] Backend responds to health check
- [ ] Frontend loads in browser
- [ ] Frontend connects to backend via ngrok
- [ ] .env files auto-created with correct values
- [ ] Subsequent runs are fast (~5 seconds)
- [ ] Database container persists data between runs
- [ ] Container runtime detected correctly (Docker/Podman)
- [ ] Cleanup function handles edge cases

---

## Quick Validation Command

Run this one-liner to test everything:

```bash
# Start, wait 10 seconds, stop, verify clean
./run-dev.sh & sleep 10 && kill -INT $! && sleep 2 && \
(ps aux | grep -E "(uvicorn|next)" | grep -v grep && echo "❌ FAIL: Processes still running" || echo "✅ PASS: Clean shutdown")
```

**Expected**: "✅ PASS: Clean shutdown"

---

## Known Good Configuration

If you want to verify against a working setup:

**backend/.env**:
```bash
DISABLE_STARTUP_INGESTION=true
OPENAI_API_KEY=sk-proj-...  # Add your actual key
```

**frontend/.env.local**:
```bash
NEXT_PUBLIC_API_URL=https://will-node.ngrok.dev
```

**Docker Compose**:
```bash
# Should have running container:
docker ps | grep semantic_db
# Expected: postgres:16 container on port 5433
```

---

## Report Results

After testing, you should be able to say:

✅ **PASS** - All tests passed, script works correctly
⚠️ **PARTIAL** - Some tests failed (specify which)
❌ **FAIL** - Major issues, script doesn't work

Please test and let me know the results! I'm particularly interested in:
1. Does Ctrl+C stop cleanly?
2. Any process restarts after stopping?
3. Are the auto-created .env files correct?
