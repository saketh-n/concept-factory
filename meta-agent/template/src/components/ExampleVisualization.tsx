import { useState } from 'react'
import { motion } from 'framer-motion'

// TOPIC: delete this file and write 2-4 real visualizations, one per
// Learn section that benefits from interaction. Pattern: small local
// state, framer-motion for transitions, self-contained, no props
// required. See cron's MinutePulse / CronFieldDiagram for reference.
export function ExampleVisualization() {
  const [count, setCount] = useState(0)

  return (
    <div className="mt-5 rounded-lg border border-white/10 bg-[#0e1017] p-5">
      <div className="mb-3 text-xs uppercase tracking-wider text-gray-500">
        Interactive demo
      </div>
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={() => setCount((c) => c + 1)}
          className="rounded-md bg-amber-500/15 px-3 py-1.5 font-mono text-sm text-amber-200 ring-1 ring-inset ring-amber-400/30 transition-colors hover:bg-amber-500/25"
        >
          Tick
        </button>
        <motion.span
          key={count}
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          className="font-mono text-2xl text-white"
        >
          {count}
        </motion.span>
      </div>
    </div>
  )
}
