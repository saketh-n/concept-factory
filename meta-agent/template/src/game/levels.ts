import type { Level } from './types'

// TOPIC: replace with 10-20 data-driven levels ordered easy -> hard,
// grouped by sub-concept (topic key). Keep levels pure data; all
// mechanics live in checkAnswer.ts and usePuzzle.ts.
export const LEVELS: Level[] = [
  {
    id: 1,
    topic: 'example',
    topicLabel: 'Example category',
    prompt: 'Type the word "hello"',
    answer: 'hello',
  },
  {
    id: 2,
    topic: 'example',
    topicLabel: 'Example category',
    prompt: 'Type the word "world"',
    answer: 'world',
  },
]

export const TOTAL_LEVELS = LEVELS.length

export function getLevel(index: number): Level {
  return LEVELS[Math.min(index, TOTAL_LEVELS - 1)]
}
