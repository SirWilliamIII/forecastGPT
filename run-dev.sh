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

    # Kill backend process and its children
    if [[ -n "${BACKEND_PID:-}" ]]; then
        log "Stopping backend (PID: $BACKEND_PID)..."
        # Kill process group to get child processes too
        kill -TERM -$BACKEND_PID 2>/dev/null || kill $BACKEND_PID 2>/dev/null || true
        # Wait a moment for graceful shutdown
        sleep 1
        # Force kill if still running
        kill -9 -$BACKEND_PID 2>/dev/null || kill -9 $BACKEND_PID 2>/dev/null || true
    fi

    # Kill frontend process and its children
    if [[ -n "${FRONTEND_PID:-}" ]]; then
        log "Stopping frontend (PID: $FRONTEND_PID)..."
        # Kill process group to get child processes too
        kill -TERM -$FRONTEND_PID 2>/dev/null || kill $FRONTEND_PID 2>/dev/null || true
        # Wait a moment for graceful shutdown
        sleep 1
        # Force kill if still running
        kill -9 -$FRONTEND_PID 2>/dev/null || kill -9 $FRONTEND_PID 2>/dev/null || true
    fi

    success "Stopped all processes. Database container still running."
    success "To stop database: $COMPOSE_CMD down"
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

cd "$SCRIPT_DIR/backend"

# Check for required environment variables
if [ ! -f ".env" ]; then
    warn "No backend/.env file found. Creating minimal .env..."
    cat > .env << 'EOF'
# Minimal configuration for development
# Set DISABLE_STARTUP_INGESTION=true to skip RSS ingestion on every restart
DISABLE_STARTUP_INGESTION=true

# Add your OpenAI API key here (required for embeddings)
# OPENAI_API_KEY=sk-...
EOF
    warn "Created backend/.env - please add OPENAI_API_KEY before running ingestion"
fi

# Check if OPENAI_API_KEY is set (warn but don't fail)
if ! grep -q "^OPENAI_API_KEY=sk-" .env 2>/dev/null; then
    warn "⚠️  OPENAI_API_KEY not configured in backend/.env"
    warn "   The server will start, but embeddings will use local stubs"
    warn "   Add your key to backend/.env: OPENAI_API_KEY=sk-..."
fi

# Clear inherited venv to prevent conflicts with uv
unset VIRTUAL_ENV

# Sync dependencies
log "Syncing backend dependencies..."
uv sync --quiet

# Backfill crypto prices if asset_returns table is empty
log "Checking crypto price data..."
PRICE_COUNT=$($CONTAINER_CMD exec semantic_db psql -U semantic -d semantic_markets -t -c "SELECT COUNT(*) FROM asset_returns;" 2>/dev/null | tr -d ' ')
if [[ "$PRICE_COUNT" == "0" || -z "$PRICE_COUNT" ]]; then
    log "Backfilling crypto prices (first run)..."
    uv run python -m ingest.backfill_crypto_returns 2>&1 | grep -E "^\[backfill\]" || true
    success "Crypto prices loaded!"
else
    success "Crypto prices already loaded ($PRICE_COUNT rows)"
fi

# Start uvicorn in background (RSS ingest runs on startup via scheduler)
# Use setsid to create new process group so we can kill all children
set -m  # Enable job control
uv run uvicorn app:app --reload --host 127.0.0.1 --port 9000 &
BACKEND_PID=$!
set +m  # Disable job control

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

# Check for frontend .env.local
if [ ! -f ".env.local" ]; then
    log "Creating frontend/.env.local with ngrok tunnel..."
    cat > .env.local << 'EOF'
# Frontend environment configuration
# Backend API URL - using ngrok tunnel for external access
NEXT_PUBLIC_API_URL=https://will-node.ngrok.dev

# For local development only, use:
# NEXT_PUBLIC_API_URL=http://localhost:9000
EOF
    success "Created frontend/.env.local with ngrok URL"
fi

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    log "Installing frontend dependencies..."
    npm install --silent
fi

# Start Next.js in background
# Use setsid to create new process group so we can kill all children
set -m  # Enable job control
npm run dev &
FRONTEND_PID=$!
set +m  # Disable job control

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

# Keep script running and monitor processes
# If either dies, trigger cleanup
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
