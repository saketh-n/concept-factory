import { Callout, Code, Section, TerminalBlock } from '../components'
import { ExampleVisualization } from '../components/ExampleVisualization'

// TOPIC: replace SECTIONS, hero copy, and section content. Target 4-6
// sections; each mixes short prose with at least one interactive
// visualization or a TerminalBlock. Prose stays tight -- the demos do
// the heavy lifting.
const SECTIONS = [
  { id: 'intro', label: 'What is it?' },
  { id: 'core', label: 'Core idea' },
]

export default function Learn() {
  return (
    <main id="top" className="mx-auto max-w-3xl px-5 pb-24 pt-12 sm:pt-16">
      <div className="mb-10 text-center">
        <p className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-amber-400">
          A pocket guide
        </p>
        <h1 className="text-4xl font-bold tracking-tight text-white sm:text-5xl">
          Concept Name
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-gray-400">
          One-sentence description of the concept and why it matters.
        </p>
      </div>

      <nav className="mb-10 flex flex-wrap justify-center gap-2">
        {SECTIONS.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            className="rounded-full border border-white/10 bg-white/[0.02] px-3 py-1 text-xs text-gray-400 transition-colors hover:border-amber-400/40 hover:text-amber-200"
          >
            {s.label}
          </a>
        ))}
      </nav>

      <div className="space-y-8">
        <Section
          id="intro"
          number={1}
          title="What is it?"
          subtitle="One-line framing of the section."
        >
          <p className="text-[0.95rem] leading-relaxed text-gray-300">
            Opening paragraph. Inline commands or syntax use{' '}
            <Code>Code</Code>; key terms get{' '}
            <strong className="text-white">strong + text-white</strong>.
          </p>
          <ExampleVisualization />
        </Section>

        <Section
          id="core"
          number={2}
          title="Core idea"
          subtitle="One-line framing of the section."
        >
          <p className="text-[0.95rem] leading-relaxed text-gray-300">
            Second section body.
          </p>
          <div className="mt-4">
            <TerminalBlock comment="# example command">
              $ echo hello
            </TerminalBlock>
          </div>
          <Callout title="Gotcha">
            <p>Use Callout for pitfalls and edge cases.</p>
          </Callout>
        </Section>
      </div>
    </main>
  )
}
