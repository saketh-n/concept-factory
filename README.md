# Concept Factory

A tiny idea board. Type a topic, generate a card, and edit its title, blurb, and
notes inline. A meta prompt at the top sets the guiding intent for the board.
Everything is persisted to disk by a FastAPI backend and reloaded on startup.

Plan generation, builds, and in-place improvements are driven by **Grok**
headless (`grok -p … --output-format streaming-json`), one session per topic.

## Prerequisites

- [Grok CLI](https://grok.x.ai) installed and on your `PATH` (or set `GROK_BIN`)
- Authenticated via `grok login`, **and** `XAI_API_KEY` in the environment
  (plan/build agents + in-concept tutor chat)
- **`XAI_MANAGEMENT_API_KEY`** for the credits HUD — this is a *Management Key*
  from [console.x.ai](https://console.x.ai) → Settings → Management Keys
  (not the same as the inference API key). The HUD reads the same prepaid
  balance as the console (`management-api.x.ai/.../prepaid/balance`).
- Optional: `XAI_TEAM_ID` if auto-detect from `XAI_API_KEY` fails

## Layout

```
concept-factory/
├── backend/      # FastAPI + JSON-file persistence + Grok driver
├── frontend/     # React + Vite + Tailwind + TypeScript
├── meta-agent/   # house-style template + generation skill
└── launch.sh     # starts both together
```

## Quick start

```bash
./launch.sh
```

- Frontend: http://localhost:5173
- Backend API docs: http://localhost:8000/docs

The script creates a Python virtualenv, installs backend deps, runs `npm install`
if needed, and starts both dev servers. Press `Ctrl+C` to stop both.

## Running the pieces separately

**Backend**
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend**
```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api/*` to the backend on port 8000.

## Persistence

State (the meta prompt + all topics) is stored in `backend/data.json`, written on
every change and loaded on startup, so your board survives restarts.
