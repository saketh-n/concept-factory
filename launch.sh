#!/usr/bin/env bash
# Launch both the FastAPI backend and the Vite frontend for Concept Factory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Pull XAI_* from a login zsh if this shell doesn't already have them
# (common when the app was started before keys were added to ~/.zshrc,
# or from a GUI/IDE that never sources ~/.zshrc).
if [ -z "${XAI_MANAGEMENT_API_KEY:-}" ] || [ -z "${XAI_API_KEY:-}" ]; then
  if command -v zsh >/dev/null 2>&1 && [ -f "${HOME}/.zshrc" ]; then
    eval "$(
      zsh -lic 'env' 2>/dev/null | awk -F= '
        $1 ~ /^XAI_/ {
          # Escape single quotes for safe eval
          val=$0; sub(/^[^=]*=/, "", val)
          gsub(/\047/, "\047\\\047\047", val)
          printf "export %s=\047%s\047\n", $1, val
        }'
    )" || true
  fi
fi

# Load repo .env if present (overrides shell for local overrides)
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if [ -z "${XAI_MANAGEMENT_API_KEY:-}" ]; then
  echo "⚠  XAI_MANAGEMENT_API_KEY is not set — credits HUD cannot read console.x.ai."
  echo "   Add it to ~/.zshrc (or .env) and restart: export XAI_MANAGEMENT_API_KEY=..."
fi

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
