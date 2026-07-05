# Reviewer checklist (self-review against this before marking ready)

## Gates (hard fail)
- [ ] `npm run lint` clean
- [ ] `npm run build` clean (tsc + vite)
- [ ] Validator returns ok for every level's canonical answer
- [ ] No new dependencies beyond template/package.json (or flagged in manifest)
- [ ] No credentials, tokens, or push logic anywhere in the repo

## Learn
- [ ] 4-6 sections, each with an interactive element or worked example
- [ ] Technically accurate; commands shown actually work as written
- [ ] Accent color applied consistently (no leftover amber unless amber chosen)
- [ ] Hero, pill nav, numbered sections match the house anatomy

## Test
- [ ] 10-20 levels, easy → hard, all tagged with sub-concept keys
- [ ] Wrong answers produce teaching feedback, not just "wrong"
- [ ] Start → playing → results loop works; Play again resets fully
- [ ] Input auto-focuses; Enter submits

## Repo
- [ ] manifest.json present and matches what was built
- [ ] README follows the regex README anatomy
- [ ] index.html title, favicon, package.json name all updated
