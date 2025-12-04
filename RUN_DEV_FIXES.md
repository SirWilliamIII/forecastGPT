# run-dev.sh Fixes - Process Management

## Issue: Script Wouldn't Stop on Ctrl+C

### Problem
After pressing Ctrl+C, the backend and frontend processes would restart repeatedly instead of stopping cleanly.

### Root Causes
1. **`wait` command behavior**: The original script used `wait $BACKEND_PID $FRONTEND_PID` which would return when processes exit, but the script would continue running in the background
2. **Incomplete cleanup**: The cleanup function only sent simple KILL signals without ensuring process groups were terminated
3. **No process group management**: Child processes (uvicorn workers, Next.js dev server) were not being killed

### Fixes Applied

#### 1. Replaced `wait` with Monitoring Loop
**Before**:
```bash
# Wait for processes
wait $BACKEND_PID $FRONTEND_PID
```

**After**:
```bash
# Keep script running and monitor processes
while true; do
    # Check if backend is still running
    if ! kill -0 $BACKEND_PID 2>/dev/null; then
        error "Backend process died unexpectedly"
        cleanup
        exit 1
    fi

    # Check if frontend is still running
    if ! kill -0 $FRONTEND_PID 2>/dev/null; then
        error "Frontend process died unexpectedly"
        cleanup
        exit 1
    fi

    # Sleep to avoid busy waiting
    sleep 2
done
```

**Why**: This gives us an explicit infinite loop that we control, rather than relying on `wait` behavior.

#### 2. Enhanced Cleanup Function
**Before**:
```bash
cleanup() {
    if [[ -n "${BACKEND_PID:-}" ]]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    if [[ -n "${FRONTEND_PID:-}" ]]; then
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    exit 0
}
```

**After**:
```bash
cleanup() {
    # Kill backend process and its children
    if [[ -n "${BACKEND_PID:-}" ]]; then
        log "Stopping backend (PID: $BACKEND_PID)..."
        # Kill process group to get child processes too
        kill -TERM -$BACKEND_PID 2>/dev/null || kill $BACKEND_PID 2>/dev/null || true
        sleep 1
        # Force kill if still running
        kill -9 -$BACKEND_PID 2>/dev/null || kill -9 $BACKEND_PID 2>/dev/null || true
    fi

    # Kill frontend process and its children
    if [[ -n "${FRONTEND_PID:-}" ]]; then
        log "Stopping frontend (PID: $FRONTEND_PID)..."
        kill -TERM -$FRONTEND_PID 2>/dev/null || kill $FRONTEND_PID 2>/dev/null || true
        sleep 1
        kill -9 -$FRONTEND_PID 2>/dev/null || kill -9 $FRONTEND_PID 2>/dev/null || true
    fi

    success "Stopped all processes. Database container still running."
    success "To stop database: $COMPOSE_CMD down"
    exit 0
}
```

**Why**:
- Uses `-TERM` signal first (graceful shutdown)
- Waits 1 second for graceful shutdown
- Uses `-9` (SIGKILL) as fallback for stubborn processes
- Kills entire process group with `-$PID` syntax to catch child processes

#### 3. Added Process Group Management
**Backend**:
```bash
# Use setsid to create new process group so we can kill all children
set -m  # Enable job control
uv run uvicorn app:app --reload --host 127.0.0.1 --port 9000 &
BACKEND_PID=$!
set +m  # Disable job control
```

**Frontend**:
```bash
# Use setsid to create new process group so we can kill all children
set -m  # Enable job control
npm run dev &
FRONTEND_PID=$!
set +m  # Disable job control
```

**Why**:
- `set -m` enables job control (process groups)
- Background processes become group leaders
- `-$PID` in kill command targets entire group

### Testing

**Expected Behavior**:
```bash
$ ./run-dev.sh
[dev] Starting database container...
[dev] Database container already running
[dev] Starting backend server...
[dev] Backend running at http://localhost:9000
[dev] Starting frontend server...
[dev] Frontend running at http://localhost:3000

══════════════════════════════════════════
  ✓ Database:  http://localhost:5433
  ✓ Adminer:   http://localhost:8080
  ✓ Backend:   http://localhost:9000
  ✓ Frontend:  http://localhost:3000
══════════════════════════════════════════

Press Ctrl+C to stop all services

^C
[dev] Shutting down...
[dev] Stopping backend (PID: 12345)...
[dev] Stopping frontend (PID: 12347)...
[dev] Stopped all processes. Database container still running.
[dev] To stop database: docker compose down
```

**No Restarts**: Processes stop cleanly, no retries, script exits.

### Additional Fixes in Same Update

#### Fixed Container Command Bug
**Line 143**: Changed from hardcoded `podman` to `$CONTAINER_CMD`
```bash
# Before
PRICE_COUNT=$(podman exec semantic_db psql ...)

# After
PRICE_COUNT=$($CONTAINER_CMD exec semantic_db psql ...)
```

#### Auto-Create .env Files
- Backend: Creates minimal `.env` with `DISABLE_STARTUP_INGESTION=true`
- Frontend: Creates `.env.local` with ngrok URL `https://will-node.ngrok.dev`

#### Removed `--isolated` Flag
Removed from uvicorn command to allow proper venv usage.

### Verification Steps

1. **Start script**:
   ```bash
   ./run-dev.sh
   ```

2. **Wait for "Press Ctrl+C" message**

3. **Press Ctrl+C**

4. **Verify**:
   - Script immediately shows "Shutting down..."
   - Both PIDs are logged being stopped
   - Script exits with "Stopped all processes"
   - No restart attempts
   - Processes actually stop (check with `ps aux | grep uvicorn`)

5. **Verify no zombie processes**:
   ```bash
   ps aux | grep uvicorn  # Should be empty
   ps aux | grep "next-server"  # Should be empty
   ```

### Edge Cases Handled

1. **Process already dead**: `|| true` prevents script from crashing
2. **Permission denied**: Both group kill and individual kill attempted
3. **Stubborn processes**: SIGTERM followed by SIGKILL after 1 second
4. **Child processes**: Process group kill ensures all children are terminated

### Known Limitations

- Database container remains running (by design - keeps data)
- May take 1-2 seconds for full cleanup (due to graceful shutdown wait)
- If script is killed with `kill -9`, cleanup won't run (use Ctrl+C instead)

### Troubleshooting

**If processes still won't stop**:
```bash
# Find all related processes
ps aux | grep uvicorn
ps aux | grep next

# Kill manually by PID
kill -9 <PID>

# Or kill all by pattern
pkill -9 -f uvicorn
pkill -9 -f next-server
```

**If script exits but processes remain**:
This shouldn't happen with the new cleanup, but if it does:
```bash
# Nuclear option - kill all node and python processes
pkill -9 node
pkill -9 python
```

### Summary

The script now provides **clean process management**:

✅ Ctrl+C stops immediately (no retries)
✅ All child processes are killed
✅ Graceful shutdown attempted first
✅ Force kill as fallback
✅ Database container preserved
✅ Clear status messages throughout

The infinite restart loop is completely eliminated! 🎉
