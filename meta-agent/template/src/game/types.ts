// Generic puzzle-game types. Extend Level with topic-specific fields
// (see cron's Level for reference: fields, gridView, acceptedShortcuts).

export type Level = {
  id: number
  /** Short category key used for results breakdown, e.g. 'wildcard' */
  topic: string
  /** Human label for the category, e.g. 'Wildcard *' */
  topicLabel: string
  /** What the player is asked to produce */
  prompt: string
  /** Canonical answer. Replace/extend per topic (string, tuple, etc.) */
  answer: string
}

export type LevelResult = {
  levelId: number
  attempts: number
}

export type PuzzleStatus = 'idle' | 'playing' | 'finished'

export type FeedbackState = 'none' | 'correct' | 'wrong'

export type CheckResult = { ok: true } | { ok: false; reason: string }

export type PuzzleSnapshot = {
  status: PuzzleStatus
  levelIndex: number
  level: Level
  attemptsThisLevel: number
  totalAttempts: number
  cleared: LevelResult[]
  feedback: FeedbackState
  feedbackMessage: string
}
