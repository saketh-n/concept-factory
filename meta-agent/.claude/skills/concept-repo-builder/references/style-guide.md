# Style guide (distilled from cron, regex, tar-compression)

## Visual language

- Dark canvas `#0b0d12`; panels `bg-white/[0.02]` with `border-white/10`,
  `rounded-2xl`, `shadow-xl shadow-black/20`.
- Terminal/code surfaces are slightly lighter: `bg-[#0e1017]`.
- One accent color family per repo, applied everywhere the reference
  repos use amber: wordmark glyphs, section numbers, active tab pill,
  primary buttons, link hovers, favicon glyph, uppercase kickers.
- Text ramp: headings `text-white`, body `text-gray-300` at
  `text-[0.95rem] leading-relaxed`, secondary `text-gray-400`, muted
  `text-gray-500`. Key terms inline: `<strong className="text-white">`.
- Mono font signals "machine text": wordmark, section numbers, syntax,
  commands, HUD counters.
- Pills everywhere: `rounded-full` for nav tabs, section jump links,
  category chips.
- Motion is subtle and functional (framer-motion): fades, small y
  offsets, scale on highlight. Respect prefers-reduced-motion (already
  handled globally in index.css).

## Learn page anatomy

1. Centered hero: mono uppercase kicker ("A pocket guide"), 4xl/5xl
   title, one-paragraph max-w-xl description.
2. Pill nav of anchor links to sections.
3. `space-y-8` stack of numbered `Section` cards ("01", "02", …), each
   with title + one-line subtitle.
4. Sections interleave short prose with interactive components. Never
   more than ~2 paragraphs of prose without something to look at or
   touch.

## Tone

- Second person, direct, no filler. "The daemon wakes up every minute
  and runs any job whose schedule matches."
- Precise terminology introduced with `Code` on first use.
- Gotchas live in `Callout`, not buried in prose.

## Test page anatomy

- Three states from the puzzle hook: StartScreen (title, pitch, rules
  list, Start button) → playing (HUD + prompt card + board + input +
  FeedbackBanner) → ResultsScreen (levels cleared, first-try count,
  per-level chips, Play again).
- Input is mono, focuses automatically on level change, clears on wrong
  answers.

## README anatomy (model: regex/README.md)

- H1 = repo name. Bulleted map of tabs; the game gets an *italicized
  name* and a one-line pitch. ASCII tree of the layout. Quick start.
  Notes section for interesting implementation details.
