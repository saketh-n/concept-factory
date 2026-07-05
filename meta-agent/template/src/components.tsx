import type { ReactNode } from 'react'

// Shared Learn-page primitives. These are stable across all concept repos —
// do NOT restyle them per topic (only the accent color may change, applied
// consistently). Topic-specific visualizations live in src/components/.

export function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-white/5 px-1.5 py-0.5 font-mono text-[0.85em] text-sky-300 ring-1 ring-inset ring-white/10">
      {children}
    </code>
  )
}

export function SyntaxBadge({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md bg-amber-500/15 px-2.5 py-1 font-mono text-sm font-medium text-amber-200 ring-1 ring-inset ring-amber-400/30">
      {children}
    </span>
  )
}

export function TerminalBlock({
  children,
  comment,
}: {
  children: ReactNode
  comment?: string
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-white/10 bg-[#0e1017] p-4 font-mono text-sm leading-relaxed text-gray-300">
      {comment && <div className="mb-2 text-xs text-gray-500">{comment}</div>}
      <pre className="whitespace-pre-wrap">{children}</pre>
    </div>
  )
}

export function Callout({
  title,
  children,
}: {
  title?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="mt-5 rounded-lg border border-amber-400/20 bg-amber-400/5 p-4">
      {title && (
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-200">
          <span aria-hidden>!</span>
          {title}
        </div>
      )}
      <div className="space-y-2 text-[0.9rem] leading-relaxed text-gray-300">
        {children}
      </div>
    </div>
  )
}

export function Section({
  id,
  number,
  title,
  subtitle,
  children,
}: {
  id: string
  number: number
  title: string
  subtitle: string
  children: ReactNode
}) {
  return (
    <section id={id} className="scroll-mt-24">
      <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6 shadow-xl shadow-black/20 sm:p-8">
        <div className="mb-5 flex items-baseline gap-3">
          <span className="font-mono text-sm font-semibold text-amber-400">
            {String(number).padStart(2, '0')}
          </span>
          <div>
            <h2 className="text-xl font-semibold text-white sm:text-2xl">
              {title}
            </h2>
            <p className="mt-1 text-sm text-gray-400">{subtitle}</p>
          </div>
        </div>
        <div>{children}</div>
      </div>
    </section>
  )
}
