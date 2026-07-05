# Harness architecture notes

You are building the harness and dashboard yourself (with Claude Code as
the builder); the generator agent runs inside it. This document pins down
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
│  │ (Agent SDK query, │        │ script, NOT an agent)    │  │
│  │ one per topic)    │        │ reads GITHUB_TOKEN from  │  │
│  │ NO token in env   │        │ its own env; runs ONLY   │  │
│  │ writes to         │        │ on dashboard Approve     │  │
│  │ workspace/<topic>/│        └──────────────────────────┘  │
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
   harness spawns the generator (Agent SDK `query()` / subprocess), pass
   an explicit, minimal `env` — do not inherit the parent env. The token
   lives only in the harness/push-worker process env (loaded from
   `.env`, git-ignored).
2. **The push worker is not an agent.** It's a ~30-line deterministic
   script: create repo via GitHub REST (`POST /user/repos`), add remote,
   push. No LLM in the loop, nothing to prompt-inject. It reads
   `process.env.GITHUB_TOKEN` (a fine-grained PAT scoped to repo
   creation + contents on your account only).
3. **Approval is the only trigger.** The Approve button in your dashboard
   flips status to `approved`; the harness then invokes the push worker.
   The agent cannot invoke it: restrict the agent's `allowedTools` to
   file tools + Bash, and deny-list `git push`/`gh` via a PreToolUse
   hook or permission callback so even a confused agent can't publish.
4. **Workspace jail.** Give each agent run `cwd: workspace/<topic>/` and
   permission rules confining file writes to that directory.

## Pipeline contract per topic

1. Harness enqueues topic → spawns agent with the topic name and the
   `concept-repo-builder` skill available (`setting_sources: ["project"]`
   so `.claude/skills/` is discovered; enable via the `skills` option).
2. Agent writes `manifest.json` first. Optionally the harness pauses
   here and surfaces the plan in the dashboard for cheap early rejection.
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
