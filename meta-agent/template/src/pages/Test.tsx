import { useCallback, useEffect, useRef, useState } from 'react'
import {
  FeedbackBanner,
  PuzzleHud,
  ResultsScreen,
  StartScreen,
} from '../game/components'
import { usePuzzle } from '../game/usePuzzle'

// TOPIC: customize StartScreen copy/rules, and render the topic-specific
// board component between the HUD and the input (where noted below).
export default function Test() {
  const puzzle = usePuzzle()
  const [input, setInput] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (puzzle.status === 'playing') {
      setInput('')
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [puzzle.levelIndex, puzzle.status])

  const begin = useCallback(() => {
    setInput('')
    puzzle.start()
    requestAnimationFrame(() => inputRef.current?.focus())
  }, [puzzle])

  const submitGuess = useCallback(() => {
    if (!input.trim()) return
    const correct = puzzle.submit(input)
    if (!correct) {
      setInput('')
    }
  }, [input, puzzle])

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    submitGuess()
  }

  if (puzzle.status === 'idle') {
    return (
      <main className="mx-auto max-w-3xl px-5 pb-24 pt-10">
        <StartScreen
          onStart={begin}
          description={<>One-sentence pitch for the game.</>}
          rules={[
            'Rule one of the game.',
            'Rule two of the game.',
            'Rule three of the game.',
          ]}
        />
      </main>
    )
  }

  if (puzzle.status === 'finished') {
    return (
      <main className="mx-auto max-w-3xl px-5 pb-24 pt-10">
        <ResultsScreen
          cleared={puzzle.cleared}
          totalAttempts={puzzle.totalAttempts}
          onPlayAgain={begin}
        />
      </main>
    )
  }

  return (
    <main className="mx-auto max-w-3xl px-5 pb-24 pt-10">
      <PuzzleHud
        levelIndex={puzzle.levelIndex}
        topicLabel={puzzle.level.topicLabel}
        totalAttempts={puzzle.totalAttempts}
      />

      <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6 shadow-xl shadow-black/20 sm:p-8">
        <p className="text-lg text-white">{puzzle.level.prompt}</p>

        {/* TOPIC: render the game board / visualization here */}

        <form onSubmit={onSubmit} className="mt-6">
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value)
              puzzle.dismissFeedback()
            }}
            placeholder="Type your answer…"
            autoComplete="off"
            spellCheck={false}
            className="w-full rounded-lg border border-white/10 bg-[#0e1017] px-4 py-3 font-mono text-sm text-white outline-none transition-colors placeholder:text-gray-600 focus:border-amber-400/50"
          />
        </form>

        <FeedbackBanner
          feedback={puzzle.feedback}
          message={puzzle.feedbackMessage}
        />
      </div>
    </main>
  )
}
