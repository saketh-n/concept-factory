#!/usr/bin/env bash
# Launch both the FastAPI backend and the Vite frontend for Concept Factory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Backend ---------------------------------------------------------------
echo "==> Setting up backend"
cd "$ROOT/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

echo "==> Starting backend on http://localhost:8000"
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

# --- Frontend --------------------------------------------------------------
echo "==> Setting up frontend"
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  npm install
fi

echo "==> Starting frontend on http://localhost:5173"
npm run dev &
FRONTEND_PID=$!

# --- Cleanup ---------------------------------------------------------------
cleanup() {
  echo ""
  echo "==> Shutting down"
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo ""
echo "Concept Factory is running:"
echo "  Frontend: http://localhost:5173"
echo "  Backend:  http://localhost:8000/docs"
echo "Press Ctrl+C to stop."
wait
