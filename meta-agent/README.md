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
skill is already at `.claude/skills/concept-repo-builder/`, which is
where both Claude Code and the Agent SDK look for project skills. In
your Agent SDK options, load it with `setting_sources=["project"]` and
enable it via the `skills` option (the SDK loads no filesystem settings
by default). Docs: https://docs.claude.com/en/docs/agent-sdk/skills

The agent's job per topic: copy `template/`, fill in everything marked
`TOPIC:`, self-verify, and stop. Publishing is the harness's job after
your approval — see ARCHITECTURE.md.

## Why a Skill and not a CLAUDE.md

Both were candidates; the Skill wins here for four reasons:

1. **It travels with your custom harness.** CLAUDE.md is Claude Code
   project memory. You're building your own agent on the Agent SDK, and
   skills are first-class there (loaded from `.claude/skills/` via
   `setting_sources`) — the same folder works unchanged whether you're
   iterating interactively in Claude Code or running headless in your
   harness. One artifact, both runtimes.
2. **Progressive disclosure fits a fat spec.** Only the skill's
   name/description sits in context until a repo-building task triggers
   it; then SKILL.md loads, and the reference files (style guide, game
   design, checklist) load only when consulted. A CLAUDE.md of this size
   would be injected into *every* turn of *every* session — including
   the many turns of a generation run that don't need style details —
   burning context and diluting attention.
3. **Skills bundle resources; CLAUDE.md is one flat file.** The spec
   here is inherently multi-file: spec + three references + (pointer to)
   the template. That's exactly the shape skills were designed for.
4. **Scoping.** Your harness repo will eventually want its own
   always-on instructions (how to run the dashboard, state-file
   conventions). That's what a *thin* CLAUDE.md in the harness repo is
   for. Keeping the generation spec in a skill means harness
   instructions and repo-generation instructions never compete.

So: skill for the generation spec (this bundle), and later a short
CLAUDE.md at your harness root for harness-development conventions —
two or three lines of which can point at this skill.

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
