import type { CheckResult, Level } from './types'

// TOPIC: replace with the real validator. Keep it a pure function --
// this is what makes the game unit-testable and auto-playable by the
// harness smoke test. Return a human-readable reason on failure
// (shown in the FeedbackBanner) that teaches, not just rejects.
export function checkAnswer(input: string, level: Level): CheckResult {
  const normalized = input.trim().toLowerCase()
  if (normalized === level.answer.toLowerCase()) {
    return { ok: true }
  }
  return {
    ok: false,
    reason: `Expected something matching "${level.prompt}" -- try again.`,
  }
}
