"""Grok driver for Concept Factory.

Each topic card gets its own subfolder under ``workspace/`` and its own
headless Grok instance. We never point the agent at the meta-agent
template folder (that would blow up token usage across ~100 parallel runs);
instead the house style is condensed into the prompt below.

This module is a *pure driver*: it knows how to run ``grok`` and build
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

# Path to the Grok CLI. Override with GROK_BIN if it isn't on PATH
# (common install location: ~/.grok/bin/grok).
GROK_BIN = os.environ.get("GROK_BIN") or shutil.which("grok") or "grok"

# Grok is I/O-bound (mostly waiting on the API) but each run spawns a
# process, so we cap concurrency to protect memory and API rate limits.
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
# Every Grok change to an app is captured as a descriptive commit so a
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
    # Grok, no npm rebuild needed to switch versions.
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
# Grok's --output-format streaming-json emits NDJSON with types:
#   text / thought / end / error  (plus occasional max_turns_reached, etc.)
# Tokens arrive one chunk at a time, so we coalesce them into display lines.
class _StreamCoalescer:
    """Buffer token-level text/thought events into skimmable log lines."""

    def __init__(self, on_line: Callable[[str], None]) -> None:
        self._emit = on_line
        self._text = ""
        self._thought = ""
        self._thought_shown = False

    def push(self, evt: dict) -> None:
        etype = evt.get("type")
        if etype == "text":
            self._flush_thought(partial=True)
            self._text += evt.get("data") or ""
            self._flush_text(force=False)
        elif etype == "thought":
            self._flush_text(force=True)
            self._thought += evt.get("data") or ""
            # Thoughts are extremely granular — surface at most one marker so
            # the log stays readable, then drop the rest of the block.
            if not self._thought_shown and len(self._thought.strip()) >= 24:
                self._emit("💭 thinking…")
                self._thought_shown = True
                self._thought = ""
        elif etype == "error":
            self._flush_all()
            msg = (evt.get("message") or evt.get("data") or "error").strip()
            if msg:
                self._emit(f"⚠ {msg}")
        elif etype == "end":
            self._flush_all()
            if evt.get("stopReason") in ("Error", "Cancelled", "MaxTurns"):
                self._emit("⚠ run ended early")
            else:
                self._emit("✓ Grok finished this turn")
        elif etype == "max_turns_reached":
            self._flush_all()
            self._emit("⚠ max turns reached")

    def _flush_text(self, force: bool) -> None:
        if not self._text:
            return
        # Emit complete lines as they form; force dumps any remainder.
        while True:
            nl = self._text.find("\n")
            if nl < 0:
                break
            line = self._text[:nl].rstrip()
            self._text = self._text[nl + 1 :]
            if line.strip():
                self._emit(line)
        if force and self._text.strip():
            self._emit(self._text.strip())
            self._text = ""
        elif not force and len(self._text) >= 160:
            # Long paragraph without newlines — emit a soft break so the UI
            # updates live rather than waiting for the whole turn.
            cut = self._text.rfind(" ", 0, 160)
            if cut < 40:
                cut = 160
            self._emit(self._text[:cut].strip())
            self._text = self._text[cut:].lstrip()

    def _flush_thought(self, partial: bool) -> None:
        # Drop residual thought buffer when we switch back to text.
        self._thought = ""
        if not partial:
            self._thought_shown = False

    def _flush_all(self) -> None:
        self._flush_text(force=True)
        self._flush_thought(partial=False)


# --- Running grok -----------------------------------------------------------
def _run_grok_once(
    prompt: str,
    cwd: Path,
    emit: Callable[[str], None],
    session_id: Optional[str],
    dangerously_skip: bool,
    permission_mode: str,
    timeout: int,
) -> dict:
    """Single attempt at a headless Grok turn. See ``run_grok``."""
    # -p / --single triggers headless mode. --always-approve is required so
    # file writes and shell commands don't hang waiting for a TTY prompt.
    cmd = [
        GROK_BIN,
        "-p",
        prompt,
        "--output-format",
        "streaming-json",
        "--always-approve",
        "--cwd",
        str(cwd),
    ]
    # Build / improve need unrestricted tool use; plan mode can stay lighter
    # but headless still needs auto-approve (already set above).
    if dangerously_skip or permission_mode in ("bypassPermissions", "auto"):
        cmd += ["--permission-mode", "bypassPermissions"]
    if session_id:
        cmd += ["--resume", session_id]

    emit("Grok session started…" if not session_id else f"Resuming Grok session {session_id[:8]}…")
    coalescer = _StreamCoalescer(emit)

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
            # Session id lives on the terminal `end` event (camelCase).
            if evt.get("sessionId"):
                result_session = evt["sessionId"]
            if evt.get("type") == "error":
                final_error = evt.get("message") or evt.get("data") or "error"
            if evt.get("type") == "end":
                stop = evt.get("stopReason") or ""
                if stop in ("Error", "Cancelled"):
                    final_error = final_error or f"stopped: {stop}"
            coalescer.push(evt)
        proc.wait()
    finally:
        timer.cancel()
        stderr_thread.join(timeout=2)

    if proc.returncode not in (0, None) and not final_error:
        detail = "".join(stderr_chunks).strip()[-500:]
        final_error = detail or f"grok exited with code {proc.returncode}"

    return {"sessionId": result_session, "error": final_error}


def _looks_like_session_error(err: Optional[str]) -> bool:
    if not err:
        return False
    low = err.lower()
    return any(
        needle in low
        for needle in (
            "session",
            "resume",
            "not found",
            "unknown session",
            "no such",
            "invalid session",
        )
    )


def run_grok(
    prompt: str,
    cwd: Path,
    on_line: Optional[Callable[[str], None]] = None,
    session_id: Optional[str] = None,
    permission_mode: str = "acceptEdits",
    dangerously_skip: bool = False,
    timeout: int = PLAN_TIMEOUT,
) -> dict:
    """Run one headless Grok turn, streaming progress via ``on_line``.

    Uses ``--output-format streaming-json`` so we can surface Grok's narration
    live. Returns ``{sessionId, error}``. Auth is Grok's own (cached OAuth or
    ``XAI_API_KEY``) — no key wiring is needed here.

    ``permission_mode`` / ``dangerously_skip`` are kept for call-site
    compatibility with the old Claude driver. Unattended factory runs always
    auto-approve tools (``--always-approve``); builds additionally request
    ``bypassPermissions``.

    If a stored ``session_id`` fails to resume (e.g. leftover Claude session
    ids from before the swap), we retry once with a fresh session.
    """
    emit = on_line or (lambda _s: None)
    result = _run_grok_once(
        prompt, cwd, emit, session_id, dangerously_skip, permission_mode, timeout
    )
    if result["error"] and session_id and _looks_like_session_error(result["error"]):
        emit("Session resume failed — starting a fresh Grok session…")
        result = _run_grok_once(
            prompt, cwd, emit, None, dangerously_skip, permission_mode, timeout
        )
    return result


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


# --- Live topic chat + credit balance (xAI HTTP API) -------------------------
# Chat Q&A uses the chat-completions API (no tools) so answers stream fast and
# never mutate the app. Improve/build still go through headless `grok`.
#
# Credits HUD reads the SAME prepaid balance as console.x.ai via the
# Management API:
#   GET https://management-api.x.ai/v1/billing/teams/{team_id}/prepaid/balance
# That endpoint requires an xAI *management key* (not the inference API key).
# Create one at: console.x.ai → Settings → Management Keys
#   export XAI_MANAGEMENT_API_KEY=...

import ssl
import time
import urllib.error
import urllib.request

XAI_API_BASE = os.environ.get("XAI_API_BASE", "https://api.x.ai/v1").rstrip("/")
XAI_MGMT_BASE = os.environ.get(
    "XAI_MANAGEMENT_API_BASE", "https://management-api.x.ai"
).rstrip("/")
CHAT_MODEL = os.environ.get("CF_CHAT_MODEL", "grok-3-mini")
# xAI reports cost_in_usd_ticks on inference; 1e9 ticks ≈ $1.00.
USD_TICKS_PER_DOLLAR = 1_000_000_000

_balance_lock = threading.Lock()
_rate_limit: dict = {}
_session_spend_usd = 0.0
_session_tokens = 0
# Cache of the console prepaid balance so the HUD can poll without hammering.
_console_balance: dict = {"ts": 0.0, "data": None, "error": None}
_CONSOLE_BALANCE_TTL = 30.0  # seconds
# Session spend ledger only (not the source of truth for remaining credits).
USAGE_FILE = Path(__file__).parent / "usage.json"


def _xai_key() -> Optional[str]:
    return os.environ.get("XAI_API_KEY") or None


def _mgmt_key() -> Optional[str]:
    """Management key for billing (console.x.ai prepaid balance)."""
    return (
        os.environ.get("XAI_MANAGEMENT_API_KEY")
        or os.environ.get("XAI_MANAGEMENT_KEY")
        or None
    )


def _ssl_context() -> ssl.SSLContext:
    """Prefer certifi's CA bundle (macOS system Python often lacks one)."""
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def ticks_to_usd(ticks: int) -> float:
    return float(ticks) / USD_TICKS_PER_DOLLAR


def _load_usage() -> dict:
    """Local session/lifetime spend ledger — NOT console remaining balance."""
    if not USAGE_FILE.is_file():
        return {}
    try:
        data = json.loads(USAGE_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_usage(data: dict) -> None:
    try:
        USAGE_FILE.write_text(json.dumps(data, indent=2) + "\n")
    except Exception:
        pass


def set_budget_usd(amount: Optional[float]) -> dict:
    """No-op kept for API compat — real balance comes from console.x.ai."""
    del amount
    return get_balance(force=True)


def _cents_obj_to_usd(obj) -> Optional[float]:
    """xAI represents money as {\"val\": \"<cents>\"} (sign-convention: credit is negative).

    Console remaining credits = -val / 100. Example: val \"-298\" → $2.98 left.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        raw = obj.get("val")
    else:
        raw = obj
    if raw is None or raw == "":
        return None
    try:
        cents = int(str(raw))
    except (TypeError, ValueError):
        try:
            cents = int(float(str(raw)))
        except (TypeError, ValueError):
            return None
    # Prepaid credit balances are stored as negative cents on the wire.
    return round((-cents) / 100.0, 4)


def _http_json(
    url: str,
    *,
    key: str,
    method: str = "GET",
    body: Optional[dict] = None,
    timeout: int = 20,
) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        raw = resp.read()
    if not raw:
        return {}
    return json.loads(raw.decode())


def _resolve_team_id() -> Optional[str]:
    """Team ID for billing — env override or /v1/me via inference API key."""
    env = (os.environ.get("XAI_TEAM_ID") or "").strip()
    if env:
        return env
    key = _xai_key()
    if not key:
        return None
    try:
        me = _http_json(f"{XAI_API_BASE}/me", key=key, timeout=15)
        return me.get("team_id") or (me.get("api_key") or {}).get("team_id")
    except Exception:
        try:
            ak = _http_json(f"{XAI_API_BASE}/api-key", key=key, timeout=15)
            return ak.get("team_id")
        except Exception:
            return None


def _money_cents(obj) -> Optional[int]:
    """Extract integer cents from an xAI money object ``{\"val\": \"…\"}``."""
    if obj is None:
        return None
    raw = obj.get("val") if isinstance(obj, dict) else obj
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        try:
            return int(float(str(raw)))
        except (TypeError, ValueError):
            return None


def _fetch_console_prepaid(team_id: str, mgmt_key: str) -> dict:
    """Live prepaid remaining from the same Management API console.x.ai uses.

    Important: ``GET …/prepaid/balance`` ``total`` is *lifetime top-ups*
    (sum of PURCHASE/AUTO_PURCHASE), NOT remaining. Remaining is:

        prepaidCredits − prepaidCreditsUsed   (invoice preview)

    Wire amounts use credit-negative cents (e.g. -3000 → $30.00 credit).
    """
    # Lifetime purchased (for "of $X" detail) — optional, best-effort.
    purchased = None
    try:
        bal = _http_json(
            f"{XAI_MGMT_BASE}/v1/billing/teams/{team_id}/prepaid/balance",
            key=mgmt_key,
            timeout=20,
        )
        purchased = _cents_obj_to_usd(bal.get("total"))
    except Exception:
        bal = None

    # Remaining comes from the current-cycle invoice preview fields that
    # console.x.ai itself surfaces on the billing page.
    prev = _http_json(
        f"{XAI_MGMT_BASE}/v1/billing/teams/{team_id}/postpaid/invoice/preview",
        key=mgmt_key,
        timeout=20,
    )
    core = prev.get("coreInvoice") or {}
    issued_cents = _money_cents(core.get("prepaidCredits"))
    used_cents = _money_cents(core.get("prepaidCreditsUsed"))

    issued = _cents_obj_to_usd(core.get("prepaidCredits"))
    if issued is None:
        issued = purchased

    # Both fields are credit-negative on the wire. Absolute dollars used:
    used = None
    if used_cents is not None:
        used = round(abs(used_cents) / 100.0, 4)

    remaining = None
    if issued_cents is not None and used_cents is not None:
        # Credit remaining in wire cents, then convert with the same rule.
        # e.g. issued=-3000, used=-2537 → remaining_cents=-463 → $4.63
        remaining = _cents_obj_to_usd({"val": str(issued_cents - used_cents)})
    elif issued is not None and used is not None:
        remaining = round(issued - used, 4)
    elif issued is not None:
        remaining = issued

    if remaining is None:
        raise RuntimeError(
            f"could not derive prepaid remaining from invoice preview: "
            f"prepaidCredits={core.get('prepaidCredits')!r} "
            f"prepaidCreditsUsed={core.get('prepaidCreditsUsed')!r}"
        )[:240]

    return {
        "remainingUsd": remaining,
        "prepaidIssuedUsd": issued,
        "prepaidUsedUsd": used,
        "teamId": team_id,
        "rawTotal": (bal or {}).get("total") if isinstance(bal, dict) else None,
        "source": "console.x.ai/management-api",
    }


def topic_context(slug: str, title: str = "", blurb: str = "") -> str:
    """Gather PLAN.md / README so the tutor knows what this concept teaches."""
    d = WORKSPACE / slug
    chunks: List[str] = []
    if title:
        chunks.append(f"TOPIC TITLE: {title}")
    if blurb:
        chunks.append(f"BLURB: {blurb}")
    for name in (PLAN_FILE, "README.md"):
        path = d / name
        if path.is_file():
            text = path.read_text(errors="replace").strip()
            if text:
                # Cap each file so the system prompt stays lean.
                chunks.append(f"===== {name} =====\n{text[:7000]}")
    return "\n\n".join(chunks) if chunks else f"TOPIC: {title or slug}"


def chat_system_prompt(context: str) -> str:
    return f"""You are a live tutor embedded in a single-concept CS learning micro-app \
(Learn pocket-guide + Test game). The student is on the concept page right now.

Your job: answer questions about THIS topic, clarify confusing bits, give \
hints on the Test game when stuck (prefer progressive hints over spoilers — \
only give the full answer if they explicitly ask), and connect ideas to what \
the app actually teaches.

Rules:
- Ground every answer in the plan/README context below. If something isn't \
covered, say so and reason carefully from first principles.
- Be concise and second-person. Prefer short paragraphs, examples, and \
worked steps over essays.
- Do NOT rewrite, redesign, or invent app code. This is Q&A, not an editor \
(there's a separate Improve tab for that).
- If they ask something off-topic, briefly redirect to the concept.

CONTEXT FOR THIS CONCEPT:
{context}"""


def _record_balance_from_headers(headers) -> None:
    """Cache rate-limit headroom (throughput) from an xAI response."""

    def _int(name: str) -> Optional[int]:
        raw = headers.get(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    rem_tok = _int("x-ratelimit-remaining-tokens")
    lim_tok = _int("x-ratelimit-limit-tokens")
    rem_req = _int("x-ratelimit-remaining-requests")
    lim_req = _int("x-ratelimit-limit-requests")
    if rem_tok is None and rem_req is None:
        return
    with _balance_lock:
        _rate_limit.update(
            {
                "remainingTokens": rem_tok,
                "limitTokens": lim_tok,
                "remainingRequests": rem_req,
                "limitRequests": lim_req,
                "updatedAt": time.time(),
            }
        )


def _bump_session_spend(usage: Optional[dict]) -> None:
    """Record dollar cost from an xAI ``usage`` block (persisted)."""
    if not usage:
        return
    ticks = usage.get("cost_in_usd_ticks") or 0
    tokens = usage.get("total_tokens") or 0
    usd = ticks_to_usd(int(ticks)) if ticks else 0.0
    if usd <= 0 and not tokens:
        return
    global _session_spend_usd, _session_tokens
    with _balance_lock:
        _session_spend_usd = round(_session_spend_usd + usd, 6)
        _session_tokens += int(tokens)
        u = _load_usage()
        u["spentUsd"] = round(float(u.get("spentUsd") or 0) + usd, 6)
        u["totalTokens"] = int(u.get("totalTokens") or 0) + int(tokens)
        u["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _save_usage(u)


def _fmt_usd(n: float, digits: int = 2) -> str:
    """Format dollars; use more precision for tiny session spends."""
    n = float(n)
    if digits == 2 and 0 < abs(n) < 0.01:
        return f"${n:.4f}"
    return f"${n:,.{digits}f}"


def _fmt_count(n: int) -> str:
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.1f}k".replace(".0k", "k")
    return str(n)


def _get_console_prepaid(force: bool = False) -> dict:
    """Fetch (or return cached) prepaid balance from management-api.x.ai.

    This is the same prepaid remaining figure shown on console.x.ai.
    Requires ``XAI_MANAGEMENT_API_KEY`` (inference API keys return 401).
    """
    now = time.time()
    with _balance_lock:
        cached = _console_balance.get("data")
        cached_err = _console_balance.get("error")
        ts = float(_console_balance.get("ts") or 0)
        if not force and (now - ts) < _CONSOLE_BALANCE_TTL and (cached or cached_err):
            if cached is not None:
                return {"ok": True, **cached}
            return {"ok": False, "error": cached_err or "unknown"}

    mgmt = _mgmt_key()
    if not mgmt:
        err = (
            "Set XAI_MANAGEMENT_API_KEY (console.x.ai → Settings → Management Keys). "
            "Inference XAI_API_KEY cannot read billing."
        )
        with _balance_lock:
            _console_balance.update({"ts": now, "data": None, "error": err})
        return {"ok": False, "error": err}

    team_id = _resolve_team_id()
    if not team_id:
        err = "Could not resolve team id (set XAI_TEAM_ID or XAI_API_KEY)"
        with _balance_lock:
            _console_balance.update({"ts": now, "data": None, "error": err})
        return {"ok": False, "error": err}

    try:
        data = _fetch_console_prepaid(team_id, mgmt)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:240]
        except Exception:
            pass
        if e.code == 401:
            err = (
                "Management key rejected (401). Create a Management Key at "
                "console.x.ai → Settings → Management Keys and export "
                "XAI_MANAGEMENT_API_KEY."
            )
        else:
            err = f"Management API HTTP {e.code}: {body or e.reason}"
        with _balance_lock:
            _console_balance.update({"ts": now, "data": None, "error": err})
        return {"ok": False, "error": err}
    except Exception as e:
        err = f"Management API error: {e}"
        with _balance_lock:
            _console_balance.update({"ts": now, "data": None, "error": err})
        return {"ok": False, "error": err}

    with _balance_lock:
        _console_balance.update({"ts": now, "data": data, "error": None})
    return {"ok": True, **data}


def get_balance(force: bool = False) -> dict:
    """Live prepaid $ remaining from console.x.ai (Management API).

    Primary source: GET management-api.x.ai/.../prepaid/balance
    (same figure as the Credits page on console.x.ai).

    Local usage.json is only used for optional session-spend detail — never
    as the remaining balance. Rate-limit tokens are headroom only.
    """
    with _balance_lock:
        usage = _load_usage()
        spent = float(usage.get("spentUsd") or 0)
        session = _session_spend_usd
        session_tok = _session_tokens
        rl = dict(_rate_limit)

    console = _get_console_prepaid(force=force)

    if not console.get("ok"):
        err = console.get("error") or "console balance unavailable"
        return {
            "ok": False,
            "currency": "USD",
            "source": "console.x.ai",
            "label": "Credits unavailable",
            "detail": err,
            "error": err,
            "spentUsd": round(spent, 6),
            "sessionSpendUsd": round(session, 6),
            "sessionTokens": session_tok,
            "budgetUsd": None,
            "remainingUsd": None,
            "prepaidIssuedUsd": None,
            "prepaidUsedUsd": None,
            "pct": None,
            "remainingTokens": rl.get("remainingTokens"),
            "limitTokens": rl.get("limitTokens"),
            "remainingRequests": rl.get("remainingRequests"),
            "limitRequests": rl.get("limitRequests"),
        }

    remaining = console.get("remainingUsd")
    issued = console.get("prepaidIssuedUsd")
    used = console.get("prepaidUsedUsd")
    if used is None and issued is not None and remaining is not None:
        used = round(max(0.0, issued - remaining), 4)

    pct = None
    if issued and issued > 0 and remaining is not None:
        pct = round(100.0 * max(0.0, remaining) / issued, 1)

    if remaining is not None:
        label = f"{_fmt_usd(max(0.0, remaining))} left"
        if remaining < 0:
            label = f"{_fmt_usd(abs(remaining))} overdrawn"
    else:
        label = "Credits"

    bits: List[str] = ["console.x.ai"]
    if used is not None and issued is not None:
        bits.append(f"{_fmt_usd(used)} of {_fmt_usd(issued)} used")
    elif used is not None:
        bits.append(f"{_fmt_usd(used)} used")
    if session > 0:
        bits.append(f"session {_fmt_usd(session)}")
    if rl.get("remainingTokens") is not None and rl.get("limitTokens"):
        bits.append(
            f"headroom {_fmt_count(rl['remainingTokens'])}/{_fmt_count(rl['limitTokens'])} tok"
        )
    elif rl.get("remainingRequests") is not None and rl.get("limitRequests"):
        bits.append(
            f"headroom {_fmt_count(rl['remainingRequests'])}/{_fmt_count(rl['limitRequests'])} req"
        )

    return {
        "ok": True,
        "currency": "USD",
        "source": console.get("source") or "console.x.ai/management-api",
        "label": label,
        "detail": " · ".join(bits),
        "spentUsd": round(float(used if used is not None else spent), 6),
        "sessionSpendUsd": round(session, 6),
        "sessionTokens": session_tok,
        "budgetUsd": issued,  # total prepaid issued (for bar / compat)
        "remainingUsd": remaining,
        "prepaidIssuedUsd": issued,
        "prepaidUsedUsd": used,
        "pct": pct,  # % of prepaid pack remaining
        "teamId": console.get("teamId"),
        "remainingTokens": rl.get("remainingTokens"),
        "limitTokens": rl.get("limitTokens"),
        "remainingRequests": rl.get("remainingRequests"),
        "limitRequests": rl.get("limitRequests"),
        "error": None,
    }


def stream_chat(
    messages: List[dict],
    on_delta: Optional[Callable[[str], None]] = None,
) -> dict:
    """Stream one tutor turn via xAI chat completions.

    ``messages`` is OpenAI-style [{role, content}, ...] including system.
    Yields text via ``on_delta``. Returns {text, error, usage}.
    """
    key = _xai_key()
    if not key:
        return {"text": "", "error": "XAI_API_KEY not set", "usage": None}

    body = json.dumps(
        {
            "model": CHAT_MODEL,
            "messages": messages,
            "stream": True,
            "temperature": 0.5,
        }
    ).encode()
    req = urllib.request.Request(
        f"{XAI_API_BASE}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    emit = on_delta or (lambda _s: None)
    parts: List[str] = []
    usage = None
    try:
        with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as resp:
            _record_balance_from_headers(resp.headers)
            while True:
                raw = resp.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    evt = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if evt.get("usage"):
                    usage = evt["usage"]
                for choice in evt.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content") or ""
                    if delta:
                        parts.append(delta)
                        emit(delta)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        return {"text": "".join(parts), "error": f"xAI {e.code}: {detail}", "usage": None}
    except Exception as e:  # noqa: BLE001
        return {"text": "".join(parts), "error": str(e), "usage": None}

    _bump_session_spend(usage)
    return {"text": "".join(parts), "error": None, "usage": usage}
