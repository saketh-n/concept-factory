# Game design notes

## What worked in the reference repos

- **cron — linear puzzle.** Prompt in plain English ("Every 10 minutes"),
  player types the five-field expression, a schedule grid visualizes
  what their answer *would* fire so wrong answers are self-explanatory.
  Pattern: type-the-syntax + live visualization of the attempt.
- **regex — Pattern Drop.** Timed falling-blocks: patterns descend, the
  player types a *matching string* (inverted recall — reading, not
  writing, the syntax). Score broken down by category.
- **tar-compression — command playground.** Free-form command input
  parsed and animated against a sample file tree; learning by
  predicting what a flag combination does.

## Design rules

- Test *recall and construction*, not recognition. Typing an answer
  beats multiple choice. If multiple choice is genuinely the right fit,
  make distractors plausible near-misses.
- Every level maps to exactly one sub-concept key; the results screen
  and any dashboard rely on that categorization.
- Difficulty curve: first 2-3 levels are near-freebies that teach the
  interface; last 2-3 combine sub-concepts.
- Wrong-answer feedback teaches: say *why* it's wrong ("that fires at
  minute 10 only, not every 10 minutes"), pulled from the pure
  validator's reason string.
- Keep the core pure and importable: `parse*`, `match*`/`checkAnswer`
  functions with no React imports. The harness smoke-test auto-plays
  level 1 by importing these directly.
- Visual board is optional but strongly preferred — it is usually the
  same visualization family as the Learn page, reused.

## Choosing a mechanic for a new topic

Ask: what would an expert *do* with this concept under mild time
pressure? Write syntax (cron-style), predict output (tar-style), or
produce an example that satisfies a constraint (regex-style). Pick the
one closest to real usage of the concept.
