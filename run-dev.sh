#!/usr/bin/env bash
set -euo pipefail

# BloombergGPT Development Runner
# Starts database, backend, and frontend in one command
#
# Performance tip: Create backend/.env with DISABLE_STARTUP_INGESTION=true
# to skip RSS/crypto ingestion on every restart (saves time and API costs)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() { echo -e "${BLUE}[dev]${NC} $1"; }
success() { echo -e "${GREEN}[dev]${NC} $1"; }
warn() { echo -e "${YELLOW}[dev]${NC} $1"; }
error() { echo -e "${RED}[dev]${NC} $1"; }

# Detect container runtime (podman or docker)
if command -v podman &> /dev/null; then
    CONTAINER_CMD="podman"
    COMPOSE_CMD="podman-compose"
    # Check if podman-compose exists, otherwise try podman compose
    if ! command -v podman-compose &> /dev/null; then
        if podman compose version &> /dev/null 2>&1; then
            COMPOSE_CMD="podman compose"
        else
            error "Neither podman-compose nor 'podman compose' found. Install with: pip install podman-compose"
            exit 1
        fi
    fi
elif command -v docker &> /dev/null; then
    CONTAINER_CMD="docker"
    COMPOSE_CMD="docker compose"
else
    error "Neither podman nor docker found. Please install one."
    exit 1
fi

log "Using container runtime: $CONTAINER_CMD"

# Check if database container is running
check_db() {
    if $CONTAINER_CMD ps --format "{{.Names}}" 2>/dev/null | grep -q "semantic_db"; then
        return 0
    else
        return 1
    fi
}

# Start database if not running
start_db() {
    if check_db; then
        success "Database container already running"
    else
        log "Starting database container..."
        $COMPOSE_CMD up -d db adminer
        
        # Wait for postgres to be ready
        log "Waiting for PostgreSQL to be ready..."
        for i in {1..30}; do
            if $CONTAINER_CMD exec semantic_db pg_isready -U semantic &> /dev/null; then
                success "PostgreSQL is ready!"
                return 0
            fi
            sleep 1
        done
        error "PostgreSQL failed to start within 30 seconds"
        exit 1
    fi
}

# Cleanup function
cleanup() {
    echo ""
    warn "Shutting down..."
    
    # Kill background processes
    if [[ -n "${BACKEND_PID:-}" ]]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    if [[ -n "${FRONTEND_PID:-}" ]]; then
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    
    success "Stopped all processes. Database container still running."
    exit 0
}

trap cleanup INT TERM

# Main execution
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║${NC}     ${GREEN}BloombergGPT${NC} Development Server      ${BLUE}║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""

# Step 1: Start database
start_db

# Step 2: Start backend
log "Starting backend server..."

# Clear inherited venv to prevent conflicts with uv
unset VIRTUAL_ENV

cd "$SCRIPT_DIR/backend"

# Sync dependencies (UV_PROJECT_ENVIRONMENT=.venv set in .zprofile)
uv sync --quiet

# Backfill crypto prices if asset_returns table is empty
log "Checking crypto price data..."
PRICE_COUNT=$(podman exec semantic_db psql -U semantic -d semantic_markets -t -c "SELECT COUNT(*) FROM asset_returns;" 2>/dev/null | tr -d ' ')
if [[ "$PRICE_COUNT" == "0" || -z "$PRICE_COUNT" ]]; then
    log "Backfilling crypto prices (first run)..."
    uv run python -m ingest.backfill_crypto_returns 2>&1 | grep -E "^\[backfill\]" || true
    success "Crypto prices loaded!"
else
    success "Crypto prices already loaded ($PRICE_COUNT rows)"
fi

# Start uvicorn in background (RSS ingest runs on startup via scheduler)
uv run --isolated uvicorn app:app --reload --host 127.0.0.1 --port 9000 &
BACKEND_PID=$!

# Wait a moment for backend to start
sleep 2

if ! kill -0 $BACKEND_PID 2>/dev/null; then
    error "Backend failed to start"
    exit 1
fi

success "Backend running at http://localhost:9000"

# Step 3: Start frontend
log "Starting frontend server..."
cd "$SCRIPT_DIR/frontend"

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    log "Installing frontend dependencies..."
    npm install --silent
fi

# Start Next.js in background
npm run dev &
FRONTEND_PID=$!

sleep 3

if ! kill -0 $FRONTEND_PID 2>/dev/null; then
    error "Frontend failed to start"
    cleanup
    exit 1
fi

success "Frontend running at http://localhost:3000"

# Print status
echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "  ${GREEN}✓${NC} Database:  http://localhost:5433"
echo -e "  ${GREEN}✓${NC} Adminer:   http://localhost:8080"
echo -e "  ${GREEN}✓${NC} Backend:   http://localhost:9000"
echo -e "  ${GREEN}✓${NC} Frontend:  http://localhost:3000"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo -e "Press ${YELLOW}Ctrl+C${NC} to stop all services"
echo ""

# Wait for processes
wait $BACKEND_PID $FRONTEND_PID
