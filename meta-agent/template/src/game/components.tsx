import type { ReactNode } from 'react'
import { TOTAL_LEVELS } from './levels'
import type { FeedbackState, LevelResult } from './types'

// Generic game-screen chrome in the house style. Stable across repos.
// The topic-specific board/visualization (cron's ScheduleGrid, tar's
// ArchiveStreamView) is a separate component rendered between the HUD
// and the input by pages/Test.tsx.

export function StartScreen({
  onStart,
  title = 'Ready to test yourself?',
  description,
  rules,
}: {
  onStart: () => void
  title?: string
  description: ReactNode
  rules: string[]
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-8 text-center shadow-xl shadow-black/20 sm:p-12">
      <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
        {title}
      </h1>
      <div className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-gray-400">
        {description}
      </div>
      <ul className="mx-auto mt-6 max-w-md space-y-2 text-left text-sm text-gray-400">
        {rules.map((rule) => (
          <li key={rule} className="flex gap-2">
            <span className="text-amber-400" aria-hidden>
              -
            </span>
            {rule}
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={onStart}
        className="mt-8 rounded-full bg-amber-500/20 px-8 py-3 font-semibold text-amber-200 ring-1 ring-inset ring-amber-400/40 transition-colors hover:bg-amber-500/30"
      >
        Start
      </button>
    </div>
  )
}

export function PuzzleHud({
  levelIndex,
  topicLabel,
  totalAttempts,
}: {
  levelIndex: number
  topicLabel: string
  totalAttempts: number
}) {
  return (
    <div className="mb-6 flex items-center justify-between gap-4 text-sm">
      <div className="flex items-center gap-3">
        <span className="font-mono font-semibold text-amber-400">
          {String(levelIndex + 1).padStart(2, '0')}
          <span className="text-gray-500">/{TOTAL_LEVELS}</span>
        </span>
        <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs text-gray-400">
          {topicLabel}
        </span>
      </div>
      <span className="text-xs text-gray-500">
        {totalAttempts} attempt{totalAttempts === 1 ? '' : 's'}
      </span>
    </div>
  )
}

export function FeedbackBanner({
  feedback,
  message,
}: {
  feedback: FeedbackState
  message: string
}) {
  if (feedback === 'none') return null
  const correct = feedback === 'correct'
  return (
    <div
      role="status"
      className={
        'mt-4 rounded-lg border p-3 text-sm ' +
        (correct
          ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'
          : 'border-rose-400/30 bg-rose-400/10 text-rose-200')
      }
    >
      {message}
    </div>
  )
}

export function ResultsScreen({
  cleared,
  totalAttempts,
  onPlayAgain,
}: {
  cleared: LevelResult[]
  totalAttempts: number
  onPlayAgain: () => void
}) {
  const perfect = cleared.filter((r) => r.attempts === 1).length
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-8 text-center shadow-xl shadow-black/20 sm:p-12">
      <p className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-amber-400">
        Run complete
      </p>
      <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
        {cleared.length}/{TOTAL_LEVELS} levels cleared
      </h1>
      <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-gray-400">
        {perfect} first-try, {totalAttempts} total attempts.
      </p>
      <div className="mx-auto mt-6 flex max-w-md flex-wrap justify-center gap-2">
        {cleared.map((r) => (
          <span
            key={r.levelId}
            className={
              'rounded-md px-2.5 py-1 font-mono text-xs ring-1 ring-inset ' +
              (r.attempts === 1
                ? 'bg-emerald-500/15 text-emerald-200 ring-emerald-400/30'
                : 'bg-white/5 text-gray-400 ring-white/10')
            }
          >
            L{r.levelId} · {r.attempts}
          </span>
        ))}
      </div>
      <button
        type="button"
        onClick={onPlayAgain}
        className="mt-8 rounded-full bg-amber-500/20 px-8 py-3 font-semibold text-amber-200 ring-1 ring-inset ring-amber-400/40 transition-colors hover:bg-amber-500/30"
      >
        Play again
      </button>
    </div>
  )
}
