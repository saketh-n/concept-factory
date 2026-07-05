# concept-template

Reference template for single-concept learning repos (Learn + Test).
Vite + React 19 + TypeScript + Tailwind 4 + framer-motion, linted with
oxlint, built with `tsc -b && vite build`.

Everything marked `TOPIC:` is a fill-in point. Everything else is stable
house style — do not restyle it.

```
src/
├── App.tsx                 # tab shell (Learn/Test) — swap wordmark + accent
├── components.tsx          # shared Learn primitives (Section, Callout, …)
├── components/             # topic-specific visualizations (one file each)
├── pages/Learn.tsx         # pocket-guide article, 4–6 numbered sections
├── pages/Test.tsx          # game screen wiring
└── game/
    ├── types.ts            # extend Level per topic
    ├── levels.ts           # pure data, 10–20 levels, easy → hard
    ├── checkAnswer.ts      # pure validator (unit-testable)
    ├── usePuzzle.ts        # generic linear puzzle loop
    └── components.tsx      # StartScreen / HUD / Feedback / Results
```

## Quick start

```bash
npm install
npm run dev
```

## Verify (the harness runs these as gates)

```bash
npm run lint
npm run build
```
