import { useEffect, useState } from "react";
import { api, type Topic } from "./api";
import TopicCard from "./components/TopicCard";
import GroupTree from "./components/GroupTree";
import PlanModal from "./components/PlanModal";

const BUSY: Topic["planStatus"][] = ["queued", "planning", "building"];

/** Pipeline order + colors for the fleet summary strip. */
const PIPELINE: { status: Topic["planStatus"]; label: string; dot: string }[] = [
  { status: "none", label: "no plan", dot: "bg-white/25" },
  { status: "queued", label: "queued", dot: "bg-slate-400" },
  { status: "planning", label: "planning", dot: "bg-violet-400" },
  { status: "ready", label: "plan ready", dot: "bg-emerald-400/70" },
  { status: "building", label: "building", dot: "bg-amber-400" },
  { status: "built", label: "built", dot: "bg-emerald-400" },
  { status: "error", label: "error", dot: "bg-rose-400" },
];

/** Merge server topics onto local, preserving object identity for unchanged
 *  cards so in-progress inline edits aren't clobbered by polling. */
function mergeTopics(prev: Topic[], next: Topic[]): Topic[] {
  const byId = new Map(prev.map((t) => [t.id, t]));
  return next.map((t) => {
    const old = byId.get(t.id);
    return old && JSON.stringify(old) === JSON.stringify(t) ? old : t;
  });
}

export default function App() {
  const [metaPrompt, setMetaPrompt] = useState("");
  const [topics, setTopics] = useState<Topic[]>([]);
  const [paste, setPaste] = useState("");
  const [loading, setLoading] = useState(true);
  const [intakeOpen, setIntakeOpen] = useState(false);
  const [openPlanId, setOpenPlanId] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const anyBusy = topics.some((t) => BUSY.includes(t.planStatus));
  const openPlan = topics.find((t) => t.id === openPlanId) ?? null;

  useEffect(() => {
    api
      .getState()
      .then((s) => {
        setMetaPrompt(s.metaPrompt);
        setTopics(s.topics);
        setIntakeOpen(s.topics.length === 0);
      })
      .finally(() => setLoading(false));
  }, []);

  // Poll while any plan/build job is running so statuses update live.
  useEffect(() => {
    if (!anyBusy) return;
    const id = window.setInterval(async () => {
      const s = await api.getState();
      setTopics((prev) => mergeTopics(prev, s.topics));
    }, 2000);
    return () => window.clearInterval(id);
  }, [anyBusy]);

  const generatePlans = async () => {
    await api.generatePlans();
    const s = await api.getState();
    setTopics((prev) => mergeTopics(prev, s.topics));
  };

  const patchTopic = (t: Topic) =>
    setTopics((prev) => prev.map((x) => (x.id === t.id ? t : x)));

  const addTopics = async () => {
    if (!paste.trim()) return;
    const created = await api.createTopicsBulk(paste);
    setTopics((prev) => [...prev, ...created]);
    setPaste("");
  };

  // Number of non-empty lines, previewed on the button.
  const pendingCount = paste
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean).length;

  const updateTopic = async (id: string, patch: Partial<Omit<Topic, "id">>) => {
    const updated = await api.updateTopic(id, patch);
    setTopics((prev) => prev.map((t) => (t.id === id ? updated : t)));
  };

  const deleteTopic = async (id: string) => {
    await api.deleteTopic(id);
    setTopics((prev) => prev.filter((t) => t.id !== id));
  };

  const clearAll = async () => {
    if (!confirm(`Delete all ${topics.length} cards? This can't be undone.`))
      return;
    await api.deleteAllTopics();
    setTopics([]);
  };

  const counts = PIPELINE.map((p) => ({
    ...p,
    n: topics.filter((t) => t.planStatus === p.status).length,
  })).filter((p) => p.n > 0);

  // Live text filter across a card's title, blurb, notes, and group path.
  // Space-separated terms are AND-ed so "python decorator" narrows further.
  const query = search.trim().toLowerCase();
  const terms = query.split(/\s+/).filter(Boolean);
  const filteredTopics = terms.length
    ? topics.filter((t) => {
        const haystack = [t.title, t.blurb, t.notes, ...t.path]
          .join(" ")
          .toLowerCase();
        return terms.every((term) => haystack.includes(term));
      })
    : topics;

  return (
    <div className="min-h-screen">
      {/* Top bar: wordmark · meta prompt · actions */}
      <header className="sticky top-0 z-10 border-b border-white/[0.07] bg-ink/85 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center gap-5 px-6 py-3">
          <span className="shrink-0 select-none font-mono text-sm font-semibold text-slate-100">
            concept<span className="text-violet-400">_</span>factory
          </span>

          <input
            className="min-w-0 flex-1 rounded-lg border border-white/[0.07] bg-well px-3.5 py-2 text-[0.83rem] text-slate-300 outline-none transition-colors placeholder:text-slate-600 focus:border-violet-400/40"
            placeholder="Meta prompt — guidance the agent applies to every topic…"
            title="Applied to every topic when planning and building"
            value={metaPrompt}
            onChange={(e) => setMetaPrompt(e.target.value)}
            onBlur={() => api.setMetaPrompt(metaPrompt)}
          />

          <button
            onClick={generatePlans}
            className="shrink-0 rounded-full bg-violet-400/15 px-4 py-1.5 text-[0.83rem] font-medium text-violet-200 ring-1 ring-inset ring-violet-400/30 transition hover:bg-violet-400/25 active:scale-95"
          >
            Generate plans
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 pb-24 pt-8">
        {/* Fleet summary: the pipeline at a glance */}
        {!loading && topics.length > 0 && (
          <div className="mb-6 flex flex-wrap items-center gap-x-5 gap-y-2">
            {counts.map((p) => (
              <span
                key={p.status}
                className="flex items-center gap-1.5 font-mono text-[11.5px] text-slate-400"
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${p.dot} ${
                    (p.status === "planning" || p.status === "building") && anyBusy
                      ? "animate-pulse"
                      : ""
                  }`}
                />
                {p.n} {p.label}
              </span>
            ))}
            <span className="ml-auto flex items-center gap-4">
              <span className="relative flex items-center">
                <span
                  className="pointer-events-none absolute left-2.5 text-slate-600"
                  aria-hidden
                >
                  ⌕
                </span>
                <input
                  className="w-44 rounded-full border border-white/[0.09] bg-well py-1 pl-7 pr-7 font-mono text-[11.5px] text-slate-300 outline-none transition-colors placeholder:text-slate-600 focus:w-56 focus:border-violet-400/40"
                  placeholder="Search cards…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setSearch("");
                  }}
                />
                {search && (
                  <button
                    onClick={() => setSearch("")}
                    title="Clear search"
                    className="absolute right-2.5 text-slate-500 transition-colors hover:text-slate-300"
                  >
                    ✕
                  </button>
                )}
              </span>
              <button
                onClick={() => setIntakeOpen((o) => !o)}
                className="font-mono text-[11.5px] text-slate-500 transition-colors hover:text-violet-300"
              >
                + add topics
              </button>
              <button
                onClick={clearAll}
                className="font-mono text-[11.5px] text-slate-600 transition-colors hover:text-rose-300"
              >
                clear all
              </button>
            </span>
          </div>
        )}

        {/* Intake: paste topics (terminal-flavored, collapsible once the
            board is populated) */}
        {(intakeOpen || topics.length === 0) && (
          <div className="mb-8 overflow-hidden rounded-xl border border-white/[0.07] bg-well">
            <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-2">
              <span className="font-mono text-[11px] uppercase tracking-[0.15em] text-slate-500">
                Paste topics · one per line
              </span>
              <span className="font-mono text-[11px] text-slate-600">
                Group &gt; Subgroup &gt; Title | notes
              </span>
            </div>
            <textarea
              className="block min-h-[8.5rem] w-full resize-y bg-transparent p-4 font-mono text-[0.83rem] leading-relaxed text-slate-300 outline-none placeholder:text-slate-600"
              placeholder={
                "Hash Tables\nLinux > Shell > Vim | modal editing basics\nProgramming Languages > Python > Decorators"
              }
              value={paste}
              onChange={(e) => setPaste(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) addTopics();
              }}
            />
            <div className="flex items-center justify-between border-t border-white/[0.06] px-4 py-2.5">
              <span className="font-mono text-[11px] text-slate-600">
                {pendingCount > 0
                  ? `${pendingCount} topic${pendingCount === 1 ? "" : "s"} · ⌘↵ to add`
                  : "deterministic split — no tokens spent"}
              </span>
              <button
                onClick={addTopics}
                disabled={pendingCount === 0}
                className="rounded-full bg-violet-400/15 px-4 py-1.5 text-[0.83rem] font-medium text-violet-200 ring-1 ring-inset ring-violet-400/30 transition hover:bg-violet-400/25 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Add {pendingCount > 0 ? pendingCount : ""} card
                {pendingCount === 1 ? "" : "s"}
              </button>
            </div>
          </div>
        )}

        {/* The board */}
        {loading ? (
          <p className="font-mono text-sm text-slate-500">loading…</p>
        ) : topics.length === 0 ? (
          <p className="text-sm text-slate-500">
            No topics yet. Paste a list above — each line becomes a card.
          </p>
        ) : filteredTopics.length === 0 ? (
          <p className="text-sm text-slate-500">
            No cards match{" "}
            <span className="font-mono text-slate-400">“{search.trim()}”</span>.{" "}
            <button
              onClick={() => setSearch("")}
              className="text-violet-300 underline-offset-2 hover:underline"
            >
              Clear search
            </button>
          </p>
        ) : (
          <GroupTree
            topics={filteredTopics}
            renderCard={(topic) => (
              <TopicCard
                key={topic.id}
                topic={topic}
                onChange={(patch) => updateTopic(topic.id, patch)}
                onDelete={() => deleteTopic(topic.id)}
                onOpenPlan={() => setOpenPlanId(topic.id)}
              />
            )}
          />
        )}
      </main>

      {openPlan && (
        <PlanModal
          topic={openPlan}
          onSaved={patchTopic}
          onClose={() => setOpenPlanId(null)}
        />
      )}
    </div>
  );
}
