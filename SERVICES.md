# BloombergGPT Auto-Start Services

Automatically run the backend and database on macOS boot using LaunchAgents.

## Quick Start

```bash
# Install and start services
./setup-services.sh install

# Check status
./setup-services.sh status

# View logs in real-time
./setup-services.sh logs
```

## What Gets Installed

### 1. Database Service (`com.bloomberggpt.database.plist`)
- **What:** PostgreSQL + Adminer via Docker Compose
- **Port:** 5433 (PostgreSQL), 8080 (Adminer)
- **Auto-start:** Yes
- **Auto-restart:** No (Docker manages containers)

### 2. Backend Service (`com.bloomberggpt.backend.plist`)
- **What:** FastAPI server with uvicorn
- **Port:** 9000
- **Auto-start:** Yes
- **Auto-restart:** Yes (crashes or exits)
- **Throttle:** Max 1 restart per 10 seconds

## Features

✅ **Auto-start on boot** - Services start when you login
✅ **Auto-restart on crash** - Backend restarts if it crashes
✅ **Persistent logging** - All output saved to `logs/` directory
✅ **Background process** - Runs without terminal windows
✅ **Proper shutdown** - Clean shutdown when you log out

## Commands

```bash
# Install services (one-time setup)
./setup-services.sh install

# Check service status
./setup-services.sh status

# View logs in real-time
./setup-services.sh logs

# Restart services
./setup-services.sh restart

# Stop services (temporary)
./setup-services.sh stop

# Start services
./setup-services.sh start

# Uninstall services completely
./setup-services.sh uninstall
```

## Log Files

All logs are stored in `logs/` directory:

- `backend-stdout.log` - Backend standard output
- `backend-stderr.log` - Backend errors
- `database-stdout.log` - Docker compose output
- `database-stderr.log` - Docker compose errors

**View logs:**
```bash
# Follow backend logs
tail -f logs/backend-stdout.log

# Check for errors
tail -50 logs/backend-stderr.log

# Or use the helper command
./setup-services.sh logs
```

## Service Locations

LaunchAgent plists are installed to:
```
~/Library/LaunchAgents/com.bloomberggpt.backend.plist
~/Library/LaunchAgents/com.bloomberggpt.database.plist
```

## Manual Service Management

If you prefer to manage services manually:

```bash
# Load/start service
launchctl load ~/Library/LaunchAgents/com.bloomberggpt.backend.plist

# Unload/stop service
launchctl unload ~/Library/LaunchAgents/com.bloomberggpt.backend.plist

# Check if service is running
launchctl list | grep bloomberggpt
```

## Troubleshooting

### Service won't start

1. **Check logs:**
   ```bash
   tail -50 logs/backend-stderr.log
   ```

2. **Verify paths in plist files:**
   - Working directory exists
   - Python venv path is correct
   - Database URL is correct

3. **Test manually first:**
   ```bash
   cd backend
   uv run uvicorn app:app --host 127.0.0.1 --port 9000
   ```

### Database connection errors

1. **Ensure Docker is running:**
   ```bash
   docker ps | grep postgres
   ```

2. **Start database manually:**
   ```bash
   docker compose up -d db adminer
   ```

3. **Check database logs:**
   ```bash
   docker compose logs db
   ```

### Want to disable auto-start?

Unload the service without removing it:
```bash
launchctl unload ~/Library/LaunchAgents/com.bloomberggpt.backend.plist
```

Re-enable:
```bash
launchctl load ~/Library/LaunchAgents/com.bloomberggpt.backend.plist
```

## Environment Variables

The backend plist includes `DATABASE_URL`. For other environment variables (API keys, etc.), you have two options:

### Option 1: Add to plist (Recommended)
Edit `com.bloomberggpt.backend.plist`:
```xml
<key>EnvironmentVariables</key>
<dict>
    <key>DATABASE_URL</key>
    <string>postgresql://semantic:semantic@localhost:5433/semantic_markets</string>
    <key>OPENAI_API_KEY</key>
    <string>sk-your-key-here</string>
    <key>WEAVIATE_URL</key>
    <string>https://your-cluster.weaviate.cloud</string>
</dict>
```

Then reload:
```bash
./setup-services.sh restart
```

### Option 2: Use backend/.env file
The backend already loads from `.env` file. Just ensure it's present:
```bash
cd backend
ls -la .env  # Should exist
```

## Performance Notes

**Startup Time:**
- Database: ~5 seconds (Docker container init)
- Backend: ~2 seconds (FastAPI + dependencies)
- **Total:** ~7 seconds after boot

**Resource Usage:**
- PostgreSQL: ~50-100MB RAM
- Backend: ~100-200MB RAM
- **Total:** ~150-300MB RAM

**Restart Policy:**
- Backend restarts automatically on crash
- Throttled to prevent restart loops (10s minimum between restarts)
- Database managed by Docker (persistent)

## Production Considerations

For production deployment, consider:

1. **Remove `--reload` flag** from backend plist (development-only)
2. **Use production WSGI server** (Gunicorn instead of uvicorn directly)
3. **Add SSL/TLS termination** (nginx reverse proxy)
4. **Set up log rotation** (prevent log files from growing indefinitely)
5. **Monitor service health** (add health check endpoint monitoring)

## Uninstalling

To completely remove services:

```bash
# Stop and uninstall
./setup-services.sh uninstall

# Optional: Remove logs
rm -rf logs/
```

This keeps your code and database data intact.
