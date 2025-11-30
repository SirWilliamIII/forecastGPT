#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

API_PORT=9000

echo "[backend] Syncing environment with uv..."
uv sync

echo "[backend] Starting FastAPI on :$API_PORT..."
uv run uvicorn app:app --reload --host 127.0.0.1 --port $API_PORT &
BACKEND_PID=$!

sleep 2

echo "[backend] Starting ngrok tunnel to :$API_PORT on will-node.ngrok.dev..."
ngrok http --domain=will-node.ngrok.dev $API_PORT &
NGROK_PID=$!

echo ""
echo "🚀 FastAPI running locally at:  http://127.0.0.1:$API_PORT"
echo "🌐 Public tunnel available at: https://will-node.ngrok.dev/"
echo ""
echo "Press CTRL+C to stop everything."

trap 'echo; echo "[backend] Stopping both processes..."; kill $BACKEND_PID $NGROK_PID 2>/dev/null || true; exit 0' INT

wait $BACKEND_PID $NGROK_PID
