import { useCallback, useReducer, useRef } from 'react'
import { checkAnswer } from './checkAnswer'
import { getLevel, TOTAL_LEVELS } from './levels'
import type {
  FeedbackState,
  LevelResult,
  PuzzleSnapshot,
  PuzzleStatus,
} from './types'

const ADVANCE_DELAY_MS = 800

// Generic linear-levels puzzle loop (start -> submit -> advance -> finish).
// Stable across repos; only checkAnswer/levels change per topic. If the
// topic calls for a different mechanic (timed, falling blocks -- see
// regex's useGameLoop), write a sibling hook rather than distorting this.
export function usePuzzle() {
  const [, forceTick] = useReducer((x) => x + 1, 0)

  const status = useRef<PuzzleStatus>('idle')
  const levelIndex = useRef(0)
  const attemptsThisLevel = useRef(0)
  const totalAttempts = useRef(0)
  const cleared = useRef<LevelResult[]>([])
  const feedback = useRef<FeedbackState>('none')
  const feedbackMessage = useRef('')
  const advanceTimer = useRef<number | null>(null)

  const clearAdvanceTimer = () => {
    if (advanceTimer.current !== null) {
      window.clearTimeout(advanceTimer.current)
      advanceTimer.current = null
    }
  }

  const snapshot = (): PuzzleSnapshot => ({
    status: status.current,
    levelIndex: levelIndex.current,
    level: getLevel(levelIndex.current),
    attemptsThisLevel: attemptsThisLevel.current,
    totalAttempts: totalAttempts.current,
    cleared: [...cleared.current],
    feedback: feedback.current,
    feedbackMessage: feedbackMessage.current,
  })

  const start = useCallback(() => {
    clearAdvanceTimer()
    status.current = 'playing'
    levelIndex.current = 0
    attemptsThisLevel.current = 0
    totalAttempts.current = 0
    cleared.current = []
    feedback.current = 'none'
    feedbackMessage.current = ''
    forceTick()
  }, [])

  const finish = useCallback(() => {
    clearAdvanceTimer()
    status.current = 'finished'
    feedback.current = 'none'
    forceTick()
  }, [])

  const advanceLevel = useCallback(() => {
    const level = getLevel(levelIndex.current)
    cleared.current.push({
      levelId: level.id,
      attempts: attemptsThisLevel.current,
    })
    attemptsThisLevel.current = 0
    feedback.current = 'none'
    feedbackMessage.current = ''

    if (levelIndex.current + 1 >= TOTAL_LEVELS) {
      finish()
      return
    }

    levelIndex.current += 1
    forceTick()
  }, [finish])

  const submit = useCallback(
    (input: string): boolean => {
      if (status.current !== 'playing') return false

      clearAdvanceTimer()
      attemptsThisLevel.current += 1
      totalAttempts.current += 1

      const level = getLevel(levelIndex.current)
      const result = checkAnswer(input, level)

      if (result.ok) {
        feedback.current = 'correct'
        feedbackMessage.current = 'Correct!'
        forceTick()
        advanceTimer.current = window.setTimeout(() => {
          advanceLevel()
        }, ADVANCE_DELAY_MS)
        return true
      }

      feedback.current = 'wrong'
      feedbackMessage.current = result.reason
      forceTick()
      return false
    },
    [advanceLevel],
  )

  const dismissFeedback = useCallback(() => {
    if (feedback.current === 'wrong') {
      feedback.current = 'none'
      feedbackMessage.current = ''
      forceTick()
    }
  }, [])

  return {
    ...snapshot(),
    start,
    submit,
    dismissFeedback,
  }
}
