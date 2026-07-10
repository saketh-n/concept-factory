# Harness architecture notes

You are building the harness and dashboard yourself (with Grok as the
builder); the generator agent runs inside it. This document pins down
the contract between the three parts so credentials and approval stay
where you want them.

## Components

```
┌────────────────────────────────────────────────────────────┐
│ Harness (your process — owns state, spawns everything)     │
│                                                            │
│  topics.json / SQLite                                      │
│  status: queued → planning → generating → verifying        │
│          → ready → approved → pushed   (or failed)         │
│                                                            │
│  ┌──────────────────┐        ┌──────────────────────────┐  │
│  │ Generator agent   │        │ Push worker (plain       │  │
│  │ (Grok headless    │        │ script, NOT an agent)    │  │
│  │ `grok -p`, one    │        │ reads GITHUB_TOKEN from  │  │
│  │ per topic)        │        │ its own env; runs ONLY   │  │
│  │ NO token in env   │        │ on dashboard Approve     │  │
│  │ writes to         │        └──────────────────────────┘  │
│  │ workspace/<topic>/│                                      │
│  └──────────────────┘                                       │
└───────────────┬────────────────────────────────────────────┘
                │ reads/writes state
        ┌───────┴────────┐
        │ Dashboard (your │  tabs: All topics | Review queue
        │ UI, FastAPI +   │  actions: Approve / Reject-with-feedback
        │ React like the  │           / Regenerate
        │ regex repo)     │  shows: manifest, screenshots, diff,
        └────────────────┘  link to `vite preview` of candidate
```

## Credential isolation (the part you called out)

The clean way to guarantee the agent can never see your GitHub token is
to make it structurally impossible, not just instructed:

1. **Don't put the token in the agent's environment at all.** When the
   harness spawns the generator (`grok -p` subprocess), pass an
   explicit, minimal `env` — do not inherit the parent env. The token
   lives only in the harness/push-worker process env (loaded from
   `.env`, git-ignored). Grok auth is separate (cached OAuth or
   `XAI_API_KEY`).
2. **The push worker is not an agent.** It's a ~30-line deterministic
   script: create repo via GitHub REST (`POST /user/repos`), add remote,
   push. No LLM in the loop, nothing to prompt-inject. It reads
   `process.env.GITHUB_TOKEN` (a fine-grained PAT scoped to repo
   creation + contents on your account only).
3. **Approval is the only trigger.** The Approve button in your dashboard
   flips status to `approved`; the harness then invokes the push worker.
   The agent cannot invoke it: restrict tools via `--tools` /
   `--disallowed-tools` or `--deny` rules so even a confused agent can't
   publish (`git push` / `gh`).
4. **Workspace jail.** Give each agent run `cwd: workspace/<topic>/`
   (via `--cwd`) and permission rules confining file writes to that
   directory.

## Pipeline contract per topic

1. Harness enqueues topic → spawns Grok headless with the topic name and
   the `concept-repo-builder` skill available (project skills under
   `.claude/skills/` / `.grok/skills/` are auto-discovered). Concept
   Factory currently embeds the house style in the plan/build prompts
   so parallel runs stay cheap.
2. Agent writes `manifest.json` / `PLAN.md` first. Optionally the harness
   pauses here and surfaces the plan in the dashboard for cheap early
   rejection.
3. Agent generates from `template/`, then self-verifies (`lint`, `build`,
   validator smoke test) with up to N repair loops.
4. Harness independently re-runs the gates (never trust the agent's
   claim), captures screenshots of `/learn` and `/test` with Playwright
   against `vite preview`, sets status `ready`.
5. You review in the dashboard. Reject-with-feedback re-invokes the
   agent with your comment appended. Approve triggers the push worker.
6. Push worker creates the repo (name from `manifest.json`), pushes,
   records the URL, status `pushed`.

## Failure handling

- Any gate failing after N repair attempts → status `failed` with the
  log attached; shows in the dashboard for manual triage.
- Keep every candidate in `workspace/<topic>/` until pushed or
  explicitly discarded, so review/regenerate is cheap.
