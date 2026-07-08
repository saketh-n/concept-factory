"""Claude Code driver for Concept Factory.

Each topic card gets its own subfolder under ``workspace/`` and its own
headless Claude Code instance. We never point the agent at the meta-agent
template folder (that would blow up token usage across ~100 parallel runs);
instead the house style is condensed into the prompt below.

This module is a *pure driver*: it knows how to run ``claude`` and build
prompts. All persisted state lives in main.py.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, List, Optional

TEMPLATE_DIR = Path(__file__).parents[1] / "meta-agent" / "template"

WORKSPACE = Path(__file__).parent / "workspace"
WORKSPACE.mkdir(exist_ok=True)

# Claude Code is I/O-bound (mostly waiting on the API) but each run spawns a
# Node process, so we cap concurrency to protect memory and API rate limits.
# 12-core / 18 GB machine → 8 in flight; the rest queue in the executor.
CONCURRENCY = int(os.environ.get("CF_PLAN_CONCURRENCY", "8"))
EXECUTOR = ThreadPoolExecutor(max_workers=CONCURRENCY)

# Per-run wall-clock ceiling (seconds).
PLAN_TIMEOUT = 420
BUILD_TIMEOUT = 1800

PLAN_FILE = "PLAN.md"


def slugify(title: str, taken: set) -> str:
    """kebab-case slug for a topic title, made unique against ``taken``."""
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "topic"
    slug = base
    i = 2
    while slug in taken:
        slug = f"{base}-{i}"
        i += 1
    return slug


def topic_dir(slug: str) -> Path:
    path = WORKSPACE / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_built(slug: str) -> bool:
    """True if a servable production bundle exists on disk for this slug.

    This is the source of truth for "built" — status reconciliation checks the
    workspace rather than trusting a possibly-stale persisted enum.
    """
    return bool(slug) and (WORKSPACE / slug / "dist" / "index.html").is_file()


# --- Prompts ----------------------------------------------------------------
def build_plan_prompt(title: str, context: str, meta_prompt: str) -> str:
    ctx = f"\nEXTRA CONTEXT FROM THE CARD: {context.strip()}" if context.strip() else ""
    meta = (
        f"\nBOARD INTENT (meta prompt steering the whole set): {meta_prompt.strip()}"
        if meta_prompt.strip()
        else ""
    )
    return f"""You are planning ONE single-concept learning micro-app. Do NOT write \
app code. Your only deliverable is a short, reviewable PLAN (like an editor's \
plan mode) for the most *memorable* way to LEARN and TEST the topic below. \
Write it to a file named `{PLAN_FILE}` in your current working directory and nothing else.

TOPIC: {title}{ctx}{meta}

WHAT GETS BUILT LATER (so your plan fits the house pattern — do not build it now):
Each topic becomes a tiny Vite + React + TypeScript + Tailwind app with two tabs:
- LEARN: an interactive "pocket guide" — a centered hero (mono uppercase kicker, \
big title, one-paragraph description), a pill nav of anchor links, then 4-6 numbered \
sections ("01", "02", ...). Prose is tight and second-person; every section carries \
at least one interactive visualization or worked example (never more than ~2 \
paragraphs without something to see or touch). Dark theme (#0b0d12 canvas, \
white/[0.02] panels), ONE accent Tailwind color family per topic, subtle \
framer-motion. Gotchas go in callouts.
- TEST: a game/puzzle that proves the concept stuck. It tests RECALL and \
CONSTRUCTION, not recognition — the player TYPES an answer or PREDICTS output, \
not multiple choice. 10-20 data-driven levels, easy -> hard (first 2-3 teach the \
interface, last 2-3 combine sub-concepts), each level tagged with exactly one \
sub-concept key so results break down by category. Wrong answers return a \
TEACHING reason (e.g. "that fires at minute 10 only, not every 10 minutes"), \
never just "wrong". Validation is a pure function.
Reference mechanics for tone: cron (type the five-field expression; a grid shows \
what it WOULD fire), regex "Pattern Drop" (timed falling patterns; type a string \
that matches), tar (type a command; watch it animate over a file tree). Choose the \
mechanic by asking: what would an expert DO with this concept under mild time \
pressure — write syntax, predict output, or satisfy a constraint? Pick whichever is \
closest to real usage.

`{PLAN_FILE}` MUST be markdown with exactly these sections:
1. `# {title} — Plan`
2. **Repo name** — kebab-case, 1-3 words, concrete (e.g. `hash-tables`, `tcp-handshake`).
3. **One-line description** — the GitHub-style tagline.
4. **Learning angle** — 2-3 sentences: the mental model / "aha" this app builds and why it sticks.
5. **Learn page** — the 4-6 numbered section titles, each with a one-line note on \
its interactive visualization or worked example.
6. **Test game** — an *italicized name*, a one-paragraph mechanic pitch, why that \
mechanic fits THIS concept, the list of sub-concept keys the levels will cover, and \
3 example levels each written as: prompt -> expected answer -> teaching reason for a \
plausible wrong answer.
7. **Accent color** — one Tailwind family (e.g. `emerald`, `sky`, `violet`), not amber.
8. **Risks / open questions** — anything a human should decide before building.

Keep it crisp: a human will skim, edit, and approve this — it is a plan, not an \
essay. Write ONLY `{PLAN_FILE}`. Do not scaffold code or create other files."""


def copy_template(dest: Path) -> None:
    """Copy the concept-template into a topic folder for building.

    Skips node_modules / build output; leaves PLAN.md in place.
    """
    if not TEMPLATE_DIR.exists():
        return
    ignore = shutil.ignore_patterns("node_modules", "dist", ".git", "*.log")
    for item in TEMPLATE_DIR.iterdir():
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True, ignore=ignore)
        else:
            shutil.copy2(item, target)


def build_prompt() -> str:
    """Instruction for turning an approved PLAN.md into a working repo.

    The concept-template has already been copied into the working directory,
    so the house style / boilerplate rules are condensed here rather than read
    from the meta-agent folder.
    """
    return f"""The concept-template (Vite + React 19 + TS + Tailwind 4 + \
framer-motion) has been copied into your current working directory, alongside an \
approved `{PLAN_FILE}`. Build the learning app described by PLAN.md by filling in \
the template — do not rebuild boilerplate.

Rules:
- Read PLAN.md first; it is the source of truth for repo name, sections, game \
mechanic, sub-concept keys, example levels, and accent color.
- Only edit files marked `TOPIC:` plus new files under `src/components/` and \
`src/game/`. Never restyle the shared primitives; the only global change is \
swapping the accent color family everywhere the template uses `amber-*`.
- LEARN (`src/pages/Learn.tsx` + `src/components/`): 4-6 numbered sections, each \
with an interactive visualization (one self-contained component per file, no \
required props, framer-motion transitions) or a worked example. Tight second-person prose.
- TEST (`src/pages/Test.tsx` + `src/game/`): 10-20 levels in `levels.ts` as pure \
data, easy -> hard, each tagged with a sub-concept key. Keep validation a pure \
function in `checkAnswer.ts` (no React imports); wrong answers return a teaching \
reason. Reuse `usePuzzle.ts` for type-the-answer games; write a sibling hook for a \
different mechanic.
- Update `index.html` title + favicon glyph, `package.json` name, and write a \
README (H1 = repo name, tab map with the game's *italic* name, ASCII layout tree, \
quick start, notes).
- Do NOT add dependencies beyond package.json. Never push, commit, or touch git.

Verify before finishing (fix and re-run until both are clean):
```
npm install
npm run lint
npm run build
```
Also smoke-test the game core: feed level 1's canonical answer through the \
validator and confirm it returns ok. Report what you built and the gate results."""


def improve_prompt(request: str) -> str:
    return (
        "The app in your current working directory is already built and working "
        "(a Vite + React + TypeScript learning app with a Learn page and a Test "
        "game). Apply this improvement without breaking what's there — change only "
        f"what's needed:\n\n{request}\n\nThen verify it still compiles cleanly:\n"
        "```\nnpm run lint\nnpm run build\n```\nFix and re-run until green, then "
        "briefly report what you changed. Do not touch git."
    )


# --- Git history ------------------------------------------------------------
# Every Claude Code change to an app is captured as a descriptive commit so a
# bad change can be rolled back. Commits are made by the backend (deterministic),
# not the agent — the house rules forbid the agent from touching git.
def _git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def _git_ensure_repo(cwd: Path) -> None:
    if (cwd / ".git").exists():
        return
    _git(["init", "-q"], cwd)
    _git(["config", "user.email", "factory@concept.local"], cwd)
    _git(["config", "user.name", "Concept Factory"], cwd)
    # Keep generated/heavy dirs out of history so commits are just source.
    gi = cwd / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    for pat in ("node_modules", "dist", ".cflogs"):
        if pat not in lines:
            lines.append(pat)
    gi.write_text("\n".join(lines) + "\n")


def seed_history(dest: Path, src: Optional[Path]) -> None:
    """Adopt a concept's real git history into its working copy.

    The workspace/runtime copies were made without .git, so review/revert
    would otherwise operate on a phantom timeline. This copies the source
    repo's .git in ONCE, then never touches it again.

    Invariant: if ``dest`` already has history, do nothing — we never replace
    or rewrite an existing timeline (that was the old overwriting bug). A
    missing or history-less ``src`` is tolerated: the concept simply starts
    its history at the first backend commit.
    """
    if (dest / ".git").exists():
        return  # already has a timeline — never overwrite it
    if not src or not (src / ".git").exists():
        return  # nothing to adopt; git_commit will init on first snapshot
    shutil.copytree(src / ".git", dest / ".git")
    # The copied index reflects src's tree, not dest's files. A mixed reset
    # realigns HEAD/index/worktree without discarding any local changes.
    _git(["reset", "--mixed", "-q", "HEAD"], dest)


def dist_base_ok(slug: str) -> bool:
    """True if the built bundle references the /concepts/<slug>/ asset base.

    A bundle built with Vite's default base ('/') will 404 its assets when
    served from the sub-path, so a False here is the signal that the bundle
    needs re-finalizing.
    """
    index = WORKSPACE / slug / "dist" / "index.html"
    if not index.is_file():
        return False
    return f"/concepts/{slug}/assets" in index.read_text()


def git_commit(cwd: Path, message: str) -> bool:
    """Snapshot the app's source as a commit (inits the repo on first use).

    Returns True if a commit was made, False if nothing changed.
    """
    _git_ensure_repo(cwd)
    _git(["add", "-A"], cwd)
    # dist/ is gitignored (it's generated), but we deliberately version the built
    # bundle too so any past version can be re-served by a plain git restore — no
    # Claude Code, no npm rebuild needed to switch versions.
    if (cwd / "dist").exists():
        _git(["add", "-f", "dist"], cwd)
    if _git(["diff", "--cached", "--quiet"], cwd).returncode == 0:
        return False  # nothing staged
    _git(["commit", "-q", "-m", message], cwd)
    return True


def has_committed_dist(cwd: Path, ref: str) -> bool:
    """True if commit ``ref`` carries a built bundle, i.e. it can be served by a
    plain git restore without rebuilding."""
    if not (cwd / ".git").exists():
        return False
    return _git(["cat-file", "-e", f"{ref}:dist/index.html"], cwd).returncode == 0


def served_hash(cwd: Path) -> str:
    """Full hash of the commit whose version is currently being served.

    Usually that's HEAD, but a revert records a synthetic ``Revert to <short>``
    commit at the tip whose content is really an earlier version — and those
    synthetic commits are hidden from the history — so resolve through it to the
    real commit the user is actually looking at.
    """
    if not (cwd / ".git").exists():
        return ""
    head = _git(["rev-parse", "HEAD"], cwd).stdout.strip()
    if not head:
        return ""
    subject = _git(["log", "-1", "--pretty=format:%s", "HEAD"], cwd).stdout.strip()
    m = re.match(r"^Revert to ([0-9a-f]{4,40})$", subject)
    if m:
        resolved = _git(
            ["rev-parse", "--verify", "--quiet", m.group(1) + "^{commit}"], cwd
        ).stdout.strip()
        if resolved:
            return resolved
    return head


# Auto-generated maintenance commits (reverts, protective snapshots) that the
# system creates for bookkeeping — not real user-facing changes, so they're
# hidden from the Versions history.
_INTERNAL_COMMIT_PREFIXES = ("Revert to ", "Snapshot before ")


def git_log(cwd: Path, n: int = 100) -> list:
    if not (cwd / ".git").exists():
        return []
    out = _git(["log", f"-{n}", "--pretty=format:%H%x1f%s%x1f%cI"], cwd).stdout
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        message = parts[1]
        if message.startswith(_INTERNAL_COMMIT_PREFIXES):
            continue
        commits.append({"hash": parts[0], "message": message, "date": parts[2]})
    return commits


def git_revert_to(cwd: Path, target: str) -> bool:
    """Restore the source to a prior commit as a NEW commit (history preserved
    so you can still go forward again)."""
    if not (cwd / ".git").exists():
        return False
    old = _git(["rev-parse", "HEAD"], cwd).stdout.strip()
    if not old or target == old:
        return False
    _git(["reset", "--hard", target], cwd)   # worktree + index -> target
    _git(["reset", "--soft", old], cwd)       # move HEAD back to tip, keep content
    if _git(["diff", "--cached", "--quiet"], cwd).returncode != 0:
        _git(["commit", "-q", "-m", f"Revert to {target[:8]}"], cwd)
    return True


def refine_prompt(feedback: str) -> str:
    return (
        "Revise PLAN.md based on this feedback. Keep the same section structure "
        "and rewrite the file in place — PLAN.md remains your only deliverable. "
        f"Feedback:\n\n{feedback}"
    )


def plan_title(plan_text: str) -> Optional[str]:
    """Pull a display title from a PLAN.md's first H1 (`# Foo — Plan` → `Foo`)."""
    for line in plan_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            title = re.sub(r"\s*[—–-]\s*Plan\s*$", "", title).strip()
            return title or None
    return None


def consolidate_prompt(plans: List[tuple], meta_prompt: str) -> str:
    """Synthesize several ready plans into ONE unified learning-app plan.

    ``plans`` is a list of (title, plan_markdown) for the selected topics.
    """
    meta = (
        f"\nBOARD INTENT (meta prompt steering the whole set): {meta_prompt.strip()}"
        if meta_prompt.strip()
        else ""
    )
    n = len(plans)
    blocks = "\n\n".join(
        f"===== SOURCE PLAN {i} — {title} =====\n{(plan or '').strip()}"
        for i, (title, plan) in enumerate(plans, 1)
    )
    return f"""You are CONSOLIDATING {n} separate single-concept learning micro-app \
plans into ONE unified plan. Each source below is a plan for its own tiny \
Vite + React + TypeScript + Tailwind learning app (a LEARN pocket-guide tab and a \
TEST game tab). Your job is to design a SINGLE app that teaches and tests ALL of \
these topics together as one coherent concept — not a menu of separate apps bolted \
together. Do NOT write app code. Your only deliverable is `{PLAN_FILE}` in your \
current working directory.{meta}

{blocks}

SYNTHESIZE, don't concatenate:
- Find the through-line that connects these topics and lead with it — the unified \
"aha" that makes learning them together stronger than learning them apart.
- Merge overlapping sub-concepts; keep every distinct one. Nothing important from \
any source plan should be dropped.
- Fold the source TEST games into ONE game whose levels span all the topics, each \
level still tagged with exactly one sub-concept key (reuse/rename the source keys \
so results break down by category across the merged set).
- Pick ONE accent Tailwind color family for the unified app.
- Keep it about the length of a SINGLE source plan — slightly longer is fine to \
cover the extra ground, but it must stay a crisp, skimmable plan, not the sum of \
all inputs. Tighten aggressively.

`{PLAN_FILE}` MUST be markdown with exactly these sections (same house pattern as a \
single-topic plan):
1. `# <Unified Title> — Plan`
2. **Repo name** — kebab-case, 1-3 words, concrete.
3. **One-line description** — the GitHub-style tagline for the combined app.
4. **Learning angle** — 2-3 sentences: the unifying mental model and why teaching \
these together sticks.
5. **Learn page** — 4-6 numbered section titles covering the merged material, each \
with a one-line note on its interactive visualization or worked example.
6. **Test game** — an *italicized name*, a one-paragraph mechanic pitch, why that \
mechanic fits the combined concept, the full list of sub-concept keys the levels \
cover (spanning all sources), and 3 example levels each written as: prompt -> \
expected answer -> teaching reason for a plausible wrong answer.
7. **Accent color** — one Tailwind family (not amber).
8. **Risks / open questions** — anything a human should decide before building, \
including any source material that was hard to unify.

Write ONLY `{PLAN_FILE}`. Do not scaffold code or create other files."""


# --- Streaming event → human-readable line ---------------------------------
def _describe_tool(name: str, inp: dict) -> str:
    if name in ("Write", "Edit", "MultiEdit"):
        fp = inp.get("file_path", "")
        return f"✎ editing {Path(fp).name}" if fp else f"✎ {name}"
    if name == "Read":
        fp = inp.get("file_path", "")
        return f"📖 reading {Path(fp).name}" if fp else "📖 reading"
    if name == "Bash":
        cmd = (inp.get("command", "") or "").replace("\n", " ")
        return f"$ {cmd[:100]}"
    if name in ("Glob", "Grep"):
        return f"🔍 {name.lower()} {inp.get('pattern', '')}"[:100]
    if name == "TodoWrite":
        return "🗂  updating task list"
    return f"⚙ {name}"


def format_event(evt: dict) -> List[str]:
    """Turn one stream-json event into zero or more display lines."""
    etype = evt.get("type")
    if etype == "system" and evt.get("subtype") == "init":
        return ["Claude Code session started…"]
    if etype == "assistant":
        lines: List[str] = []
        for block in evt.get("message", {}).get("content", []):
            btype = block.get("type")
            if btype == "text":
                text = (block.get("text") or "").strip()
                if text:
                    lines.append(text)
            elif btype == "thinking":
                text = (block.get("thinking") or "").strip()
                if text:
                    lines.append("💭 " + text)
            elif btype == "tool_use":
                lines.append(_describe_tool(block.get("name", ""), block.get("input", {}) or {}))
        return lines
    if etype == "result":
        if evt.get("is_error"):
            return ["⚠ run ended with an error"]
        return ["✓ Claude Code finished this turn"]
    return []


# --- Running claude ---------------------------------------------------------
def run_claude(
    prompt: str,
    cwd: Path,
    on_line: Optional[Callable[[str], None]] = None,
    session_id: Optional[str] = None,
    permission_mode: str = "acceptEdits",
    dangerously_skip: bool = False,
    timeout: int = PLAN_TIMEOUT,
) -> dict:
    """Run one headless Claude Code turn, streaming progress via ``on_line``.

    Uses --output-format stream-json so we can surface Claude's narration and
    tool calls live (the same detail the CLI shows). Returns {sessionId, error}.
    Claude Code carries its own auth, so no API key wiring is needed here.
    """
    emit = on_line or (lambda _s: None)
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if dangerously_skip:
        cmd.append("--dangerously-skip-permissions")
    else:
        cmd += ["--permission-mode", permission_mode]
    if session_id:
        cmd += ["--resume", session_id]

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stderr_chunks: List[str] = []
    stderr_thread = threading.Thread(
        target=lambda: stderr_chunks.extend(proc.stderr or []), daemon=True
    )
    stderr_thread.start()

    # Hard wall-clock kill so a hung run can't stall a worker forever.
    timer = threading.Timer(timeout, proc.kill)
    timer.start()

    result_session = session_id
    final_error: Optional[str] = None
    try:
        for raw in proc.stdout or []:
            line = raw.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("session_id"):
                result_session = evt["session_id"]
            if evt.get("type") == "result" and evt.get("is_error"):
                final_error = evt.get("subtype") or "error"
            for msg in format_event(evt):
                emit(msg)
        proc.wait()
    finally:
        timer.cancel()
        stderr_thread.join(timeout=2)

    if proc.returncode not in (0, None) and not final_error:
        detail = "".join(stderr_chunks).strip()[-500:]
        final_error = detail or f"claude exited with code {proc.returncode}"

    return {"sessionId": result_session, "error": final_error}


# --- Serving the built concept ----------------------------------------------
def patch_router_basename(cwd: Path) -> None:
    """Give BrowserRouter a basename so the built app works under a sub-path.

    The template uses absolute routes (/learn, /test) with a plain
    <BrowserRouter>; served from /concepts/<slug>/ that breaks unless the
    router knows its base. import.meta.env.BASE_URL matches the Vite --base.
    """
    main = cwd / "src" / "main.tsx"
    if not main.exists():
        return
    txt = main.read_text()
    if "basename=" in txt:
        return
    patched = txt.replace(
        "<BrowserRouter>",
        "<BrowserRouter basename={import.meta.env.BASE_URL}>",
    )
    if patched != txt:
        main.write_text(patched)


def finalize_build(cwd: Path, base: str, on_line: Callable[[str], None]) -> bool:
    """Produce a sub-path-correct production build we can serve from FastAPI."""
    patch_router_basename(cwd)
    if not (cwd / "node_modules").exists():
        on_line("$ npm install")
        subprocess.run(
            ["npm", "install"], cwd=str(cwd), capture_output=True, text=True, timeout=900
        )
    on_line(f"$ npm run build -- --base={base}")
    proc = subprocess.run(
        ["npm", "run", "build", "--", f"--base={base}"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=900,
    )
    ok = proc.returncode == 0 and (cwd / "dist" / "index.html").exists()
    if ok:
        on_line("✓ production build ready to serve")
    else:
        on_line((proc.stderr or proc.stdout or "build failed").strip()[-400:])
    return ok
