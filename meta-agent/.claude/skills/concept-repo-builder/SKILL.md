---
name: concept-repo-builder
description: Build a single-concept CS learning repo (Learn page + Test game) in the house style from the concept-template. Use whenever asked to generate, scaffold, or revise a learning repo for a CS topic (e.g. cron, regex, tar, hashing, TCP). Covers repo structure, visual style, game design, naming, and the quality gates the output must pass before it is queued for human review.
---

# Concept Repo Builder

Build one repo per CS concept. Each repo is a small Vite + React app with
two tabs: **Learn** (an interactive pocket-guide article) and **Test** (a
game/puzzle that proves the concept stuck). Reference implementations:
`cron`, `regex`, `tar-compression`.

## Workflow

1. **Plan first, write second.** Produce `manifest.json` at the repo root
   before any code:

   ```json
   {
     "topic": "<topic as given>",
     "repoName": "<kebab-case, 1-3 words, concrete: 'cron', 'tar-compression'>",
     "description": "<one-line GitHub description>",
     "sections": ["<Learn section titles, 4-6>"],
     "visualizations": ["<one line per planned interactive component>"],
     "game": { "name": "<game title>", "mechanic": "<one-paragraph pitch>", "levelCount": 0 },
     "accent": "<tailwind color family, e.g. 'emerald'>"
   }
   ```

   The harness may pause here for plan approval. If feedback arrives,
   revise the manifest before generating code.

2. **Copy the template.** Start from `template/` verbatim. Do not
   regenerate boilerplate (configs, `index.css`, `components.tsx`,
   `game/usePuzzle.ts`, `game/components.tsx`). Only touch files
   containing a `TOPIC:` marker plus new files under `src/components/`
   and `src/game/`.

3. **Write the Learn page.** 4-6 numbered `Section`s. Rules:
   - Prose is tight; interactive demos carry the teaching. Every section
     has at least one visualization, `TerminalBlock`, or worked example.
   - One visualization component per file in `src/components/`,
     self-contained, no required props, `framer-motion` for transitions.
   - Example code shown to the learner must be real and runnable
     (`TerminalBlock` with a `# comment` header where helpful).
   - Use `Callout` for gotchas, `Code` for inline syntax, `SyntaxBadge`
     for pattern chips.

4. **Write the game.** Data-driven, always:
   - 10-20 levels in `levels.ts` as pure data, easy → hard, each tagged
     with a sub-concept `topic` key so results break down by category.
   - Validation is a pure function (`checkAnswer.ts` or equivalent) —
     never validate inside components. Wrong answers return a *teaching*
     reason, not just "wrong".
   - Reuse `usePuzzle.ts` for linear type-the-answer games. For a
     different mechanic (timed, falling, drag), write a sibling hook;
     keep the pure-core / hook / components layering.

5. **Style the accent.** Pick one Tailwind color family per topic and
   replace every `amber-*` occurrence consistently (App shell, sections,
   buttons, favicon). Reference repos used amber (cron) — pick something
   the recent repos haven't used.

6. **Finish the repo.** Update `index.html` title, favicon glyph,
   `package.json` name, and write a README in the style of the regex
   README: what each tab is, the game's name in italics, quick start,
   and a Notes section for implementation details worth knowing.

7. **Self-verify before reporting done.** Both must pass clean:

   ```bash
   npm run lint
   npm run build
   ```

   Also sanity-check the game core: feed level 1's canonical answer
   through the validator and confirm it returns ok. Fix and re-run until
   green; only then mark the repo ready for review.

## Hard rules

- Never push, commit to remote, or touch git credentials. Output is a
  local candidate repo; the human-approved harness handles publishing.
- Never invent new boilerplate, dependencies, or build tooling. The
  dependency list in `template/package.json` is closed — adding a
  package requires flagging it in the manifest for human review.
- Never restyle shared primitives; only the accent family changes.

## Detail references (read as needed)

- `references/style-guide.md` — visual language, tone, layout patterns
- `references/game-design.md` — mechanics that worked, level design
- `references/review-checklist.md` — what the human reviewer checks;
  self-review against it before marking ready
