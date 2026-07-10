import { useEffect, useState } from "react";
import { api, type Topic } from "./api";
import TopicCard from "./components/TopicCard";
import WorldMap from "./components/WorldMap";
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
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [consolidating, setConsolidating] = useState(false);
  // Merge choreography: source cards collapse away (exiting → hidden) while the
  // new consolidated card rises in and streams its plan.
  const [exitingIds, setExitingIds] = useState<Set<string>>(new Set());
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());
  const [mergeTargetId, setMergeTargetId] = useState<string | null>(null);

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

  const toggleSelect = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const consolidate = async () => {
    const ids = [...selected];
    if (ids.length < 2) return;
    setConsolidating(true);
    try {
      const created = await api.consolidateTopics(ids);
      // 1) Show the new card immediately with its entrance animation, and start
      //    the sources collapsing away.
      setTopics((prev) => [...prev, created]);
      setMergeTargetId(created.id);
      setExitingIds(new Set(ids));
      setSelected(new Set());
      // 2) After the collapse animation, remove the sources from the board and
      //    open the plan modal so the Claude Code run streams live.
      window.setTimeout(() => {
        setHiddenIds((prev) => new Set([...prev, ...ids]));
        setExitingIds(new Set());
        setOpenPlanId(created.id);
      }, 620);
    } catch (e) {
      alert(`Consolidation failed: ${(e as Error).message}`);
    } finally {
      setConsolidating(false);
    }
  };

  // Resolve the merge once the new card settles: on success the sources are
  // already gone server-side (drop the hidden veil); on error, restore them.
  useEffect(() => {
    if (!mergeTargetId) return;
    const target = topics.find((t) => t.id === mergeTargetId);
    if (!target) return;
    if (target.planStatus === "error") {
      setHiddenIds(new Set());
      setMergeTargetId(null);
    } else if (target.planStatus === "ready" || target.planStatus === "built") {
      setHiddenIds(new Set());
      setMergeTargetId(null);
    }
  }, [topics, mergeTargetId]);

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

  // Hide source cards that have merged away (or are mid-collapse the moment
  // they finish animating) so they vanish cleanly into the consolidated card.
  const boardTopics = topics.filter((t) => !hiddenIds.has(t.id));

  // Live text filter across a card's title, blurb, notes, and group path.
  // Space-separated terms are AND-ed so "python decorator" narrows further.
  const query = search.trim().toLowerCase();
  const terms = query.split(/\s+/).filter(Boolean);
  const filteredTopics = terms.length
    ? boardTopics.filter((t) => {
        const haystack = [t.title, t.blurb, t.notes, ...t.path]
          .join(" ")
          .toLowerCase();
        return terms.every((term) => haystack.includes(term));
      })
    : boardTopics;

  return (
    <div className="min-h-screen game-shell">
      {/* Top bar: wordmark · meta prompt · actions */}
      <header className="sticky top-0 z-10 border-b border-white/10 bg-[#0e1a2e]/90 shadow-[0_4px_24px_rgba(0,0,0,0.3)] backdrop-blur-md">
        <div className="mx-auto flex max-w-5xl items-center gap-5 px-6 py-3">
          <span className="shrink-0 select-none font-display text-[0.95rem] font-semibold leading-none tracking-tight text-[#e8f5d8]">
            <span className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full bg-[#5DCF7A] shadow-[0_0_0_3px_rgba(93,207,122,0.25)]" aria-hidden />
            Concept<span className="text-[#8FBF6A]">Factory</span>
          </span>

          <input
            className="min-w-0 flex-1 rounded-full border border-white/10 bg-black/25 px-4 py-2 text-[0.83rem] text-slate-300 outline-none transition-colors placeholder:text-slate-600 focus:border-[#8FBF6A]/50"
            placeholder="Meta prompt — guidance the agent applies to every topic…"
            title="Applied to every topic when planning and building"
            value={metaPrompt}
            onChange={(e) => setMetaPrompt(e.target.value)}
            onBlur={() => api.setMetaPrompt(metaPrompt)}
          />

          <button
            onClick={consolidate}
            disabled={selected.size < 2 || consolidating}
            title={
              selected.size < 2
                ? "Tick the checkboxes on two or more plan-ready cards to merge them"
                : `Merge the ${selected.size} selected plans into one`
            }
            className="shrink-0 rounded-full border border-white/15 bg-white/[0.06] px-3.5 py-1.5 text-xs font-medium text-slate-300 transition hover:bg-white/[0.1] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-40 enabled:border-[#B07AE0]/45 enabled:bg-[#B07AE0]/15 enabled:text-[#e0b0ff]"
          >
            {consolidating
              ? "Merging…"
              : `Merge${selected.size >= 2 ? ` ×${selected.size}` : ""}`}
          </button>

          <button
            onClick={generatePlans}
            className="shrink-0 rounded-full bg-[#5DCF7A] px-4 py-1.5 text-xs font-semibold text-[#0e1a14] shadow-[0_3px_0_#3a9a55] transition hover:brightness-105 active:translate-y-px active:shadow-none"
          >
            Generate plans
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 pb-24 pt-8">
        {/* Fleet summary: the pipeline at a glance */}
        {!loading && topics.length > 0 && (
          <div className="mb-5 flex flex-wrap items-center gap-x-5 gap-y-2">
            {counts.map((p) => (
              <span
                key={p.status}
                className="flex items-center gap-1.5 text-[11px] font-medium text-slate-300"
              >
                <span
                  className={`h-2 w-2 rounded-sm ${p.dot} ${
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
                  className="w-44 rounded border-2 border-white/10 bg-black/30 py-1 pl-7 pr-7 font-mono text-[11.5px] text-slate-300 outline-none transition-colors placeholder:text-slate-600 focus:w-56 focus:border-[#f8d878]/40"
                  placeholder="Search worlds…"
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
                className="text-[11px] font-medium text-[#8FBF6A] transition-colors hover:text-[#b0d890]"
              >
                + Add topics
              </button>
              <button
                onClick={clearAll}
                className="text-[11px] font-medium text-slate-500 transition-colors hover:text-rose-300"
              >
                Clear all
              </button>
            </span>
          </div>
        )}

        {/* Intake: paste topics (terminal-flavored, collapsible once the
            board is populated) */}
        {(intakeOpen || topics.length === 0) && (
          <div className="mb-8 overflow-hidden rounded-xl border-2 border-white/10 bg-black/25">
            <div className="flex items-center justify-between border-b border-white/[0.06] bg-[#1a1a2e]/80 px-4 py-2">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-[#8FBF6A]">
                Paste topics · one per line
              </span>
              <span className="font-mono text-[11px] text-slate-600">
                World &gt; Course &gt; Level | notes
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
                className="rounded-full bg-[#5DCF7A] px-4 py-1.5 text-xs font-semibold text-[#0e1a14] shadow-[0_3px_0_#3a9a55] transition hover:brightness-105 active:translate-y-px active:shadow-none disabled:cursor-not-allowed disabled:opacity-40"
              >
                Add {pendingCount > 0 ? pendingCount : ""} card
                {pendingCount === 1 ? "" : "s"}
              </button>
            </div>
          </div>
        )}

        {/* The overworld / world map board */}
        {loading ? (
          <p className="text-sm text-slate-500">Loading island…</p>
        ) : topics.length === 0 ? (
          <p className="text-sm text-slate-500">
            No topics yet. Paste a list above — each line becomes a level on the map.
          </p>
        ) : filteredTopics.length === 0 ? (
          <p className="text-sm text-slate-500">
            No worlds match{" "}
            <span className="font-mono text-slate-400">“{search.trim()}”</span>.{" "}
            <button
              onClick={() => setSearch("")}
              className="text-[#5c94fc] underline-offset-2 hover:underline"
            >
              Clear search
            </button>
          </p>
        ) : (
          <WorldMap
            topics={filteredTopics}
            renderCard={(topic) => (
              <TopicCard
                key={topic.id}
                topic={topic}
                onChange={(patch) => updateTopic(topic.id, patch)}
                onDelete={() => deleteTopic(topic.id)}
                onOpenPlan={() => setOpenPlanId(topic.id)}
                selected={selected.has(topic.id)}
                onToggleSelect={() => toggleSelect(topic.id)}
                merging={exitingIds.has(topic.id)}
                entering={topic.id === mergeTargetId}
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
