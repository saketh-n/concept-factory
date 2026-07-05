import { useEffect, useState } from "react";
import { api, type Topic } from "./api";
import TopicCard from "./components/TopicCard";
import PlanModal from "./components/PlanModal";

const BUSY: Topic["planStatus"][] = ["queued", "planning", "building"];

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
  const [openPlanId, setOpenPlanId] = useState<string | null>(null);

  const anyBusy = topics.some((t) => BUSY.includes(t.planStatus));
  const openPlan = topics.find((t) => t.id === openPlanId) ?? null;

  useEffect(() => {
    api
      .getState()
      .then((s) => {
        setMetaPrompt(s.metaPrompt);
        setTopics(s.topics);
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

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      {/* Meta prompt bar */}
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto max-w-5xl px-6 py-4">
          <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-400">
            Meta Prompt
          </label>
          <input
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-indigo-300 focus:ring-2 focus:ring-indigo-200"
            placeholder="The guiding prompt for this whole board..."
            value={metaPrompt}
            onChange={(e) => setMetaPrompt(e.target.value)}
            onBlur={() => api.setMetaPrompt(metaPrompt)}
          />
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8">
        <h1 className="mb-1 text-2xl font-bold tracking-tight">Concept Factory</h1>
        <p className="mb-6 text-sm text-slate-500">
          Paste a list of topics — one per line — to generate a card for each.
          Every field is editable and saved automatically.
        </p>

        {/* Bulk paste input */}
        <div className="mb-8 flex flex-col gap-2">
          <textarea
            className="min-h-[9rem] w-full resize-y rounded-xl border border-slate-200 bg-white p-4 font-mono text-sm shadow-sm outline-none focus:border-indigo-300 focus:ring-2 focus:ring-indigo-200 placeholder:text-slate-300"
            placeholder={
              "Paste topics here, one per line, e.g.\n\nData Structures & Algos\nHash Tables\nTrees\nThreads & Concurrency"
            }
            value={paste}
            onChange={(e) => setPaste(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) addTopics();
            }}
          />
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">
              {pendingCount > 0
                ? `${pendingCount} topic${pendingCount === 1 ? "" : "s"} ready · ⌘/Ctrl+Enter to add`
                : "One topic per line"}
            </span>
            <button
              onClick={addTopics}
              disabled={pendingCount === 0}
              className="rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-indigo-700 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Generate cards
            </button>
          </div>
        </div>

        {/* Cards header */}
        {!loading && topics.length > 0 && (
          <div className="mb-4 flex items-center justify-between">
            <span className="text-sm font-medium text-slate-500">
              {topics.length} card{topics.length === 1 ? "" : "s"}
              {anyBusy && (
                <span className="ml-2 text-indigo-500">· generating…</span>
              )}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={generatePlans}
                className="rounded-lg bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white shadow-sm transition hover:bg-indigo-700 active:scale-95"
              >
                Generate plans
              </button>
              <button
                onClick={clearAll}
                className="rounded-lg border border-red-200 px-3 py-1.5 text-sm font-medium text-red-600 transition hover:bg-red-50 active:scale-95"
              >
                Clear all
              </button>
            </div>
          </div>
        )}

        {/* Cards */}
        {loading ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : topics.length === 0 ? (
          <p className="text-sm text-slate-400">
            No topics yet — create your first one above.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {topics.map((topic) => (
              <TopicCard
                key={topic.id}
                topic={topic}
                onChange={(patch) => updateTopic(topic.id, patch)}
                onDelete={() => deleteTopic(topic.id)}
                onOpenPlan={() => setOpenPlanId(topic.id)}
              />
            ))}
          </div>
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
