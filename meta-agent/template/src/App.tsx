import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import Learn from './pages/Learn'
import Test from './pages/Test'

const TABS = [
  { to: '/learn', label: 'Learn' },
  { to: '/test', label: 'Test' },
]

// TOPIC: replace the wordmark text below. Keep the accent-glyph + mono
// wordmark pattern (e.g. "*cron*"). Accent color: swap amber-* classes
// for this topic's accent throughout the app.
function App() {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-white/10 bg-[#0b0d12]/80 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-x-6 px-5 py-3">
          <NavLink
            to="/learn"
            className="font-mono text-sm font-semibold text-white"
          >
            <span className="text-amber-400">?</span>concept
            <span className="text-amber-400">?</span>
          </NavLink>
          <nav className="flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.03] p-1 text-sm">
            {TABS.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                className={({ isActive }) =>
                  'rounded-full px-4 py-1.5 transition-colors ' +
                  (isActive
                    ? 'bg-amber-500/20 text-amber-200 ring-1 ring-inset ring-amber-400/40'
                    : 'text-gray-400 hover:text-amber-200')
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <Routes>
        <Route path="/" element={<Navigate to="/learn" replace />} />
        <Route path="/learn" element={<Learn />} />
        <Route path="/test" element={<Test />} />
        <Route path="*" element={<Navigate to="/learn" replace />} />
      </Routes>
    </div>
  )
}

export default App
