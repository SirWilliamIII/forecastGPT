#!/bin/bash
# Railway deployment start script

echo "Starting BloombergGPT backend..."

# Install uv if not present
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    pip install uv
fi

# Navigate to backend directory
cd backend

# Sync dependencies
echo "Syncing dependencies..."
uv sync --frozen

# Start the application
echo "Starting uvicorn server on port ${PORT:-9000}..."
uv run uvicorn app:app --host 0.0.0.0 --port ${PORT:-9000}
