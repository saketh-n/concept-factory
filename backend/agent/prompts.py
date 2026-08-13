"""Prompt builders for plan/build/improve/refine/consolidate jobs."""


from __future__ import annotations


import re


from typing import List, Optional


from .workspace import PLAN_FILE


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
