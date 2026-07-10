# meta-agent

Everything the generator agent needs to build single-concept CS learning
repos in your house style, plus the architecture notes for the harness
you're building around it.

```
meta-agent/
├── README.md                  ← you are here
├── ARCHITECTURE.md            ← harness / dashboard / credential design
├── .claude/
│   └── skills/
│       └── concept-repo-builder/
│           ├── SKILL.md               ← the generation spec (entry point)
│           └── references/
│               ├── style-guide.md     ← visual language + tone, distilled
│               ├── game-design.md     ← mechanics + level-design rules
│               └── review-checklist.md← gates; agent self-reviews against it
└── template/                  ← buildable reference repo (concept-template)
    └── …                        Vite + React 19 + TS + Tailwind 4, verified
                                 with `npm run lint` and `npm run build`
```

## How to use

Drop this folder's contents into the root of your harness repo. The
skill lives at `.claude/skills/concept-repo-builder/`; Grok discovers
project skills from both `.grok/skills/` and `.claude/skills/` (Claude
compat), so the same folder works whether you're iterating interactively
in Grok or running headless via the Concept Factory harness.

The Concept Factory backend drives Grok headless (`grok -p …`) with the
house style condensed into the plan/build prompts in `backend/agent.py`,
so parallel topic runs never have to load the full meta-agent tree.

The agent's job per topic: copy `template/`, fill in everything marked
`TOPIC:`, self-verify, and stop. Publishing is the harness's job after
your approval — see ARCHITECTURE.md.

## Why a Skill and not always-on project rules

Both were candidates; the Skill wins here for four reasons:

1. **It travels with your custom harness.** Always-on project rules
   (AGENTS.md / CLAUDE.md) inject into every turn. You're running many
   headless Grok sessions in parallel, and skills are first-class there —
   progressive disclosure means the fat generation spec only loads when
   a repo-building task actually needs it.
2. **Progressive disclosure fits a fat spec.** Only the skill's
   name/description sits in context until a repo-building task triggers
   it; then SKILL.md loads, and the reference files (style guide, game
   design, checklist) load only when consulted. Dumping this whole
   package into every turn of every session would burn context and
   dilute attention.
3. **Skills bundle resources; a flat rules file is one file.** The spec
   here is inherently multi-file: spec + three references + (pointer to)
   the template. That's exactly the shape skills were designed for.
4. **Scoping.** Your harness repo will eventually want its own
   always-on instructions (how to run the dashboard, state-file
   conventions). That's what a thin AGENTS.md / project rules file is
   for. Keeping the generation spec in a skill means harness
   instructions and repo-generation instructions never compete.

So: skill for the generation spec (this bundle), and later a short
project rules file at your harness root for harness-development
conventions — two or three lines of which can point at this skill.

## The template

`template/` is a distilled, buildable composite of your cron, regex, and
tar-compression repos: identical configs and boilerplate, generic
versions of the shared Learn primitives and the puzzle engine
(`usePuzzle` is your `useCronPuzzle` with the validator factored out
into a pure `checkAnswer`), and `TOPIC:` markers at every fill-in point.
Dependency versions are pinned to the ranges your repos already use —
keep them pinned so generated repos stop drifting.

Verify locally:

```bash
cd template && npm install && npm run lint && npm run build
```
