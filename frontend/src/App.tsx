import { useEffect, useState } from "react";
import { api, type Topic } from "./api";
import TopicCard from "./components/TopicCard";
import WorldMap from "./components/WorldMap";
import GroupTree from "./components/GroupTree";
import PlanModal from "./components/PlanModal";
import SettingsModal from "./components/SettingsModal";
import Workbench, { isPlanMode } from "./components/Workbench";
import CreditsHud from "./components/CreditsHud";
import {
  IconMap,
  IconMerge,
  IconPlus,
  IconRows,
  IconSearch,
  IconSettings,
  IconSparkles,
  IconTrash,
  IconX,
  LogoMark,
} from "./components/icons";

const BUSY: Topic["planStatus"][] = ["queued", "planning", "building"];

type BoardView = "cards" | "map";
const VIEW_LS = "conceptFactory.boardView";
const WORKBENCH_LS = "conceptFactory.workbenchOpen";

function loadView(): BoardView {
  try {
    const v = localStorage.getItem(VIEW_LS);
    if (v === "cards" || v === "map") return v;
  } catch {
    /* ignore */
  }
  return "map";
}

function loadWorkbenchOpen(): boolean {
  try {
    const v = localStorage.getItem(WORKBENCH_LS);
    if (v === "0") return false;
    if (v === "1") return true;
  } catch {
    /* ignore */
  }
  return true; // default open so plan-mode cards are never hidden
}

/** Pipeline order + colors for the fleet summary strip. */
const PIPELINE: { status: Topic["planStatus"]; label: string; dot: string }[] = [
  { status: "none", label: "no plan", dot: "bg-slate-500" },
  { status: "queued", label: "queued", dot: "bg-slate-400" },
  { status: "planning", label: "planning", dot: "bg-violet-400" },
  { status: "ready", label: "plan ready", dot: "bg-sky-400" },
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
  // Cards (GroupTree) ↔ Map (Three.js overworld). Persisted so the choice sticks.
  const [view, setView] = useState<BoardView>(loadView);
  // Map-mode tray of plan-mode cards — open by default so new topics aren't lost.
  const [workbenchOpen, setWorkbenchOpen] = useState(loadWorkbenchOpen);
  // Soft-highlight freshly added cards in the workbench for a few seconds.
  const [freshIds, setFreshIds] = useState<Set<string>>(new Set());
  const [settingsOpen, setSettingsOpen] = useState(false);

  const anyBusy = topics.some((t) => BUSY.includes(t.planStatus));
  const openPlan = topics.find((t) => t.id === openPlanId) ?? null;

  useEffect(() => {
    try {
      localStorage.setItem(VIEW_LS, view);
    } catch {
      /* ignore */
    }
  }, [view]);

  useEffect(() => {
    try {
      localStorage.setItem(WORKBENCH_LS, workbenchOpen ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [workbenchOpen]);

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
    if (created.length === 0) return;
    setTopics((prev) => [...prev, ...created]);
    setPaste("");
    // Surface new cards: open the workbench (map view) and flash-highlight them.
    // Plan-mode cards never appear as finished cottages, so this is the landing pad.
    setWorkbenchOpen(true);
    const ids = new Set(created.map((t) => t.id));
    setFreshIds(ids);
    window.setTimeout(() => {
      setFreshIds((prev) => {
        const next = new Set(prev);
        for (const id of ids) next.delete(id);
        return next;
      });
    }, 4500);
    // Scroll workbench / board into view after layout.
    window.setTimeout(() => {
      document
        .getElementById("board-anchor")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 50);
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
      setWorkbenchOpen(true); // merged plan lands in plan mode — keep it visible on map
      setExitingIds(new Set(ids));
      setSelected(new Set());
      // 2) After the collapse animation, remove the sources from the board and
      //    open the plan modal so the Grok run streams live.
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

  // Plan-mode cards (everything not yet built) for the map-mode workbench.
  const workbenchTopics = filteredTopics.filter((t) => isPlanMode(t.planStatus));

  const renderCard = (topic: Topic) => (
    <TopicCard
      key={topic.id}
      topic={topic}
      onChange={(patch) => updateTopic(topic.id, patch)}
      onDelete={() => deleteTopic(topic.id)}
      onOpenPlan={() => setOpenPlanId(topic.id)}
      selected={selected.has(topic.id)}
      onToggleSelect={() => toggleSelect(topic.id)}
      merging={exitingIds.has(topic.id)}
      entering={topic.id === mergeTargetId || freshIds.has(topic.id)}
    />
  );

  return (
    <div className="app-shell min-h-screen">
      {/* App bar: settings · brand · studio direction · actions · credits */}
      <header className="sticky top-0 z-10 border-b border-white/[0.07] bg-[#0b101c]/85 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:gap-4 sm:px-6">
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="btn-ghost shrink-0 !px-2 !py-1.5 text-slate-400 hover:text-slate-100"
            title="Agent settings"
            aria-label="Open agent settings"
          >
            <IconSettings size={16} />
          </button>

          <a
            href="/"
            className="flex shrink-0 select-none items-center gap-2.5"
            title="Concept Factory"
          >
            <LogoMark size={24} />
            <span className="hidden font-display text-[15px] font-semibold leading-none tracking-tight text-slate-50 md:inline">
              Concept Factory
            </span>
          </a>

          <div className="relative min-w-0 flex-1 md:mx-4 md:max-w-2xl">
            <span
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
              aria-hidden
            >
              <IconSparkles size={13} />
            </span>
            <input
              className="field w-full rounded-full py-1.5 pr-4 text-[13px]"
              style={{ paddingLeft: "2.1rem" }}
              placeholder="Meta prompt — guidance the agent applies to every topic…"
              title="Applied to every topic when planning and building"
              value={metaPrompt}
              onChange={(e) => setMetaPrompt(e.target.value)}
              onBlur={() => api.setMetaPrompt(metaPrompt)}
            />
          </div>

          <div className="ml-auto flex shrink-0 items-center gap-2">
            <button
              onClick={consolidate}
              disabled={selected.size < 2 || consolidating}
              title={
                selected.size < 2
                  ? "Tick the checkboxes on two or more plan-ready cards to merge them"
                  : `Merge the ${selected.size} selected plans into one`
              }
              className={`btn-secondary ${
                selected.size >= 2
                  ? "!border-violet-400/40 !bg-violet-400/10 !text-violet-200"
                  : ""
              }`}
            >
              <IconMerge size={13} />
              {consolidating
                ? "Merging…"
                : `Merge${selected.size >= 2 ? ` ${selected.size}` : ""}`}
            </button>

            <button onClick={generatePlans} className="btn-primary">
              <IconSparkles size={13} />
              Generate plans
            </button>

            <CreditsHud variant="header" />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 pb-24 pt-6 sm:px-6">
        {/* Toolbar: view switch · pipeline census · search · library actions */}
        {!loading && topics.length > 0 && (
          <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-3">
            <div className="view-toggle" role="group" aria-label="Board view">
              <button
                type="button"
                onClick={() => setView("map")}
                aria-pressed={view === "map"}
                className={view === "map" ? "is-active" : ""}
                title="3D overworld map"
              >
                <IconMap size={13} />
                Map
              </button>
              <button
                type="button"
                onClick={() => setView("cards")}
                aria-pressed={view === "cards"}
                className={view === "cards" ? "is-active" : ""}
                title="Card list with group tree"
              >
                <IconRows size={13} />
                Cards
                {workbenchTopics.length > 0 && view !== "cards" ? (
                  <span className="view-toggle-badge">
                    {workbenchTopics.length}
                  </span>
                ) : null}
              </button>
            </div>

            <div
              className="flex flex-wrap items-center gap-x-4 gap-y-1.5"
              aria-label="Pipeline summary"
            >
              {counts.map((p) => (
                <span
                  key={p.status}
                  className="flex items-center gap-1.5 text-[12px] font-medium text-slate-400"
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${p.dot} ${
                      (p.status === "planning" || p.status === "building") &&
                      anyBusy
                        ? "animate-pulse"
                        : ""
                    }`}
                  />
                  <span className="tabular-nums text-slate-200">{p.n}</span>
                  {p.label}
                </span>
              ))}
            </div>

            <span className="ml-auto flex items-center gap-2">
              <span className="relative flex items-center">
                <span
                  className="pointer-events-none absolute left-2.5 text-slate-500"
                  aria-hidden
                >
                  <IconSearch size={13} />
                </span>
                <input
                  className="field w-44 py-1.5 pl-8 pr-7 text-[12.5px] transition-all focus:w-56 sm:w-48"
                  placeholder={view === "map" ? "Search worlds…" : "Search cards…"}
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
                    className="absolute right-2 text-slate-500 transition-colors hover:text-slate-300"
                  >
                    <IconX size={12} />
                  </button>
                )}
              </span>

              <button
                onClick={() => setIntakeOpen((o) => !o)}
                className={`btn-secondary ${intakeOpen ? "!border-emerald-400/40 !bg-emerald-400/10 !text-emerald-200" : ""}`}
              >
                <IconPlus size={13} />
                Add topics
              </button>

              <button
                onClick={clearAll}
                className="btn-ghost !px-2 text-slate-500 hover:!bg-rose-400/10 hover:!text-rose-300"
                title="Delete every card"
              >
                <IconTrash size={13} />
              </button>
            </span>
          </div>
        )}

        {/* Intake: paste topics (collapsible once the board is populated) */}
        {(intakeOpen || (!loading && topics.length === 0)) && (
          <div className="mb-8 overflow-hidden rounded-xl border border-white/[0.08] bg-panel shadow-card">
            <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-2.5">
              <span className="flex items-center gap-2 text-[12px] font-semibold text-slate-200">
                <span className="grid h-5 w-5 place-items-center rounded-md bg-emerald-400/15 text-emerald-300">
                  <IconPlus size={11} />
                </span>
                Add topics
                <span className="font-normal text-slate-500">
                  · one per line
                </span>
              </span>
              <span className="font-mono text-[11px] text-slate-600">
                World &gt; Course &gt; Level&nbsp;
                <span className="text-slate-700">|</span>&nbsp;notes
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
            <div className="flex items-center justify-between border-t border-white/[0.06] bg-white/[0.015] px-4 py-2.5">
              <span className="flex items-center gap-2 text-[11.5px] text-slate-500">
                {pendingCount > 0 ? (
                  <>
                    {pendingCount} topic{pendingCount === 1 ? "" : "s"} ready
                    <span className="flex items-center gap-1">
                      <span className="kbd">⌘</span>
                      <span className="kbd">↵</span>
                    </span>
                  </>
                ) : (
                  "Deterministic split — no tokens spent"
                )}
              </span>
              <button
                onClick={addTopics}
                disabled={pendingCount === 0}
                className="btn-primary"
              >
                Add {pendingCount > 0 ? pendingCount : ""} card
                {pendingCount === 1 ? "" : "s"}
              </button>
            </div>
          </div>
        )}

        {/* Board: card tree or 3D overworld (+ workbench for plan-mode cards) */}
        <div id="board-anchor">
          {loading ? (
            <div className="space-y-3" aria-label="Loading">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-20 animate-pulse rounded-xl border border-white/[0.05] bg-white/[0.03]"
                  style={{ animationDelay: `${i * 150}ms` }}
                />
              ))}
            </div>
          ) : topics.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-white/10 px-6 py-14 text-center">
              <LogoMark size={34} />
              <p className="mt-2 font-display text-[15px] font-semibold text-slate-200">
                Start your library
              </p>
              <p className="max-w-sm text-[13px] leading-relaxed text-slate-500">
                Paste a list of topics above — each line becomes a card
                {view === "map" ? " and a stop on the map" : ""}, and the agent
                plans and builds an interactive concept for each one.
              </p>
            </div>
          ) : filteredTopics.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-white/10 px-6 py-12 text-center">
              <p className="text-sm text-slate-400">
                No {view === "map" ? "worlds" : "cards"} match{" "}
                <span className="font-mono text-slate-200">
                  “{search.trim()}”
                </span>
              </p>
              <button onClick={() => setSearch("")} className="btn-secondary">
                Clear search
              </button>
            </div>
          ) : view === "cards" ? (
            <GroupTree topics={filteredTopics} renderCard={renderCard} />
          ) : (
            <>
              <WorldMap topics={filteredTopics} renderCard={renderCard} />
              <Workbench
                topics={workbenchTopics}
                open={workbenchOpen}
                onToggle={() => setWorkbenchOpen((o) => !o)}
                highlightIds={freshIds}
                renderCard={renderCard}
              />
            </>
          )}
        </div>
      </main>

      {openPlan && (
        <PlanModal
          topic={openPlan}
          onSaved={patchTopic}
          onClose={() => setOpenPlanId(null)}
        />
      )}

      {settingsOpen && (
        <SettingsModal onClose={() => setSettingsOpen(false)} />
      )}
    </div>
  );
}
