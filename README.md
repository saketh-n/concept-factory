# Concept Factory

An **agentic workflow platform**: a harness that orchestrates parallel headless LLM
agent sessions to plan, generate, verify, and iteratively improve complete web
apps — with a human-in-the-loop review dashboard, independent quality gates, git-based
versioning with one-click revert, and live API spend tracking.

The current output domain is single-concept CS learning apps (an interactive **Learn**
guide plus a **Test** game per topic, e.g. cron, regex, tar), but the harness itself is
domain-agnostic: swap the plan/build prompts and the template and it will factory
anything.

## How it works

```
┌─────────────────────────────────────────────────────────────────┐
│ Harness (FastAPI backend — owns all state, spawns everything)   │
│                                                                 │
│  topic lifecycle:  none → queued → planning → plan ready        │
│                    → building → built   (or error)              │
│                                                                 │
│  ┌───────────────────────┐   ┌──────────────────────────────┐  │
│  │ Generator agents      │   │ Verification & serving       │  │
│  │ headless Grok CLI,    │   │ harness re-runs lint/build   │  │
│  │ one session per topic,│   │ itself, patches the router   │  │
│  │ concurrency-capped    │   │ base, finalizes a bundle,    │  │
│  │ thread pool, hard     │   │ serves it at /concepts/<slug>│  │
│  │ wall-clock timeouts,  │   │ — never trusts the agent's   │  │
│  │ NDJSON stream → live  │   │ self-reported success        │  │
│  │ telemetry in the UI   │   └──────────────────────────────┘  │
│  └───────────────────────┘                                     │
└───────────────┬─────────────────────────────────────────────────┘
                │
        ┌───────┴────────┐
        │ Dashboard       │  React + TypeScript + Tailwind
        │ (frontend/)     │  card board + Three.js-style world map,
        └────────────────┘  plan review/edit, streaming agent logs,
                            per-concept improve chat, version history,
                            credits HUD with budget caps
```

### The pipeline, per topic

1. **Plan.** The harness spawns a headless agent whose only deliverable is a short,
   reviewable `PLAN.md` — repo name, learning angle, section outline, game mechanic,
   sub-concept keys, example levels, accent color. Cheap to generate, cheap to reject.
2. **Review.** You read, edit, or refine the plan in the dashboard
   (reject-with-feedback re-invokes the agent with your comments). Multiple plans can
   be **consolidated** into one unified plan for a combined app.
3. **Build.** On approval, the harness copies the house template into the topic's
   workspace and spawns a build session. Agents are confined to their workspace and
   forbidden (by prompt contract *and* by design — see below) from touching git or
   credentials.
4. **Verify.** The harness independently runs `npm install`, `lint`, and `build`,
   patches the router basename for sub-path serving, and finalizes a production
   bundle. Disk is the source of truth: status is reconciled against what actually
   exists in the workspace, not against what any agent claimed.
5. **Serve & iterate.** Built concepts are served at `/concepts/<slug>/` with an
   injected widget for in-app improve requests and version history. Improvement
   prompts run against the same session; every change lands as a backend-owned git
   commit, so any version can be restored (and re-served instantly — built bundles
   are committed too) with one click.

### Design decisions worth knowing

- **Never trust the agent's self-report.** Agents are instructed to self-verify, but
  the harness re-runs every gate itself before a concept is marked built. `is_built()`
  checks the workspace on disk, not a persisted status enum.
- **Agents never touch git or secrets.** All commits are made deterministically by the
  backend (`backend/agent.py`), which also hides synthetic maintenance commits
  (reverts, protective snapshots) from the user-facing history. The publishing design
  (see `meta-agent/ARCHITECTURE.md`) keeps tokens structurally outside the agent
  environment: minimal spawned env, and a plain non-agent push worker gated on
  explicit human approval.
- **Cost is a first-class signal.** The credits HUD reads the xAI management API for
  the real prepaid balance, tracks per-session spend, and enforces a user-set budget.
- **Skill-based generation spec.** The house style lives in a progressive-disclosure
  skill (`meta-agent/.claude/skills/concept-repo-builder/`) — spec, style guide, game
  design rules, and a review checklist — with a condensed version embedded in the
  headless prompts so ~parallel runs stay cheap. `meta-agent/README.md` documents why
  a skill beats always-on project rules here.
- **Resilient headless runs.** Concurrency-capped executor, per-run wall-clock kill
  timers, session-resume with automatic fresh-session fallback, and NDJSON stream
  coalescing so the dashboard shows live agent narration.
- **Every run is instrumented and persisted.** Each plan/build/improve run writes
  `backend/runs/<run_id>/` — `run.json` (duration, tokens in/out, dollar cost,
  driver+model, turns/tool calls, retries, verification-gate outcomes),
  `events.ndjson` (the raw agent stream, replayable in other tools), and `log.txt`
  (the human-readable session log). The dashboard's **Runs** view charts cost,
  duration, tokens, gate pass/fail, and per-level validator pass rates, with
  drill-in log/event viewers and one-click JSON/NDJSON/TXT export
  (`GET /api/runs`, `/api/runs/{id}/export`). Gates are harness-run: `npm run
  lint`, the production build, and a validator that auto-plays every game level's
  canonical answer through the concept's own pure `checkAnswer`.
- **Full-stack concepts too.** Concepts with their own backends run on demand from
  copy-on-write runtime copies on remapped ports (`backend/launcher.py`).

## Layout

```
concept-factory/
├── backend/      # FastAPI harness: state, agent driver, verification, git,
│                 # serving, credits, per-concept tutor chat (SSE)
├── frontend/     # React + Vite + TypeScript + Tailwind dashboard
├── meta-agent/   # generation skill, house-style template, harness architecture notes
└── launch.sh     # starts backend + frontend together
```

## Quick start

**Prerequisites**

- Grok CLI (`grok` binary) on your `$PATH` (or set `GROK_BIN=/path/to/grok`). Run `grok login` once.
- `XAI_API_KEY` in your shell environment (or in `~/.grok/config.toml`).
- `XAI_MANAGEMENT_API_KEY` (create a Management Key at https://console.x.ai → Settings → API Keys). Optional: `XAI_TEAM_ID`.
- Node.js 20+ and Python 3.9+.

```bash
# One command to rule them all
./launch.sh
```

This creates a Python venv, installs deps, runs `npm install` in frontend/, starts the FastAPI backend (port 8000) + Vite dev server (port 5173), and opens the dashboard.

- **Dashboard**: http://localhost:5173 (3D overworld + plan review + Runs metrics)
- **Backend API docs**: http://localhost:8000/docs
- **Stop**: Ctrl+C in the terminal (kills both processes cleanly)

State lives in `backend/data.json`. All generated concepts land in `backend/workspace/`.

### Grok / Help features

- **In-app Help**: Click the **?** button (top-right) for keyboard shortcuts, slash commands, troubleshooting, and Grok-specific tips.
- **Project skills**: The `concept-repo-builder` skill (in `meta-agent/.claude/skills/`) is auto-loaded by the harness for all generation tasks. See `meta-agent/README.md`.
- **CLI help cache**: Backend caches `grok --help` / `claude --help` output for speed (see `backend/agent.py`).
- **Plan mode**: Use the floating Workbench tray or `/plan` in the Grok CLI for structured generation.

See **Troubleshooting** and **Keyboard Shortcuts** sections below for common issues and power-user tips.

## Troubleshooting

**Common issues & fixes**

- **"No Grok binary found"**: Run `which grok` or set `GROK_BIN=$(which grok)` . The settings catalog probes `grok --help`.
- **Credits HUD shows $0**: Double-check `XAI_MANAGEMENT_API_KEY`. Try the Refresh button in Settings.
- **Builds fail on first run**: `npm install` can be slow on cold cache — the launcher retries. Check `frontend/dist/` after a build.
- **Agent loops forever**: Wall-clock timeouts in `backend/runs.py` kill after ~10 min. Check `backend/runs/<id>/log.txt`.
- **Dashboard stuck on "planning"**: Refresh the page or restart `./launch.sh`. State is reconciled from disk on startup.
- **Permission errors**: The backend uses `--permission-mode` from Grok CLI. See Settings modal.

**Grok-specific tips (this project uses Grok Build heavily)**

- Use the `concept-repo-builder` skill for new CS topics.
- In the Grok CLI: `/plan`, `/build`, `/improve`, or just describe the concept.
- Keyboard shortcuts (also in the in-app Help modal):
  - `?` — Open help
  - `Cmd/Ctrl + K` — Focus search / quick add topic
  - `Esc` — Close modals
  - `1/2/3` — Switch board views (Cards / Map / Runs)
- For headless parallel runs the harness manages concurrency and verification gates.

Report issues in the Runs dashboard (export JSON/NDJSON/logs with one click).

## Roadmap

- **Deeper eval harness** — the per-level validator + gate metrics now ship in the
  Runs dashboard; still to come: Playwright screenshot capture of built apps and
  rubric-based scoring against the review checklist
- **Approve → publish worker** — the deterministic, non-agent GitHub push worker
  specified in `meta-agent/ARCHITECTURE.md`
- **Hosted deployment** — public gallery of built concepts, containerized agent runs,
  and gated generation with hard budget caps
- **Model-agnostic driver** — the harness has already run on both Claude Code and
  Grok headless; factoring the driver behind a provider interface is next
