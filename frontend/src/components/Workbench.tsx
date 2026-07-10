import type { ReactNode } from "react";
import type { Topic } from "../api";

/**
 * Always-visible tray of plan-mode cards while you're on the 3D map.
 *
 * Built concepts live on the overworld; everything still in the planning
 * pipeline (none → ready → building, plus errors) sits here so a freshly
 * pasted topic is never "lost" behind cottages you have to walk to.
 */

const PLAN_MODE: Topic["planStatus"][] = [
  "none",
  "queued",
  "planning",
  "ready",
  "building",
  "error",
];

export function isPlanMode(status: Topic["planStatus"]): boolean {
  return PLAN_MODE.includes(status);
}

const STATUS_CHIP: Partial<
  Record<Topic["planStatus"], { label: string; cls: string }>
> = {
  none: { label: "no plan", cls: "bg-white/10 text-slate-300" },
  queued: { label: "queued", cls: "bg-slate-400/15 text-slate-300" },
  planning: {
    label: "planning",
    cls: "bg-violet-400/15 text-violet-200 animate-pulse",
  },
  ready: { label: "plan ready", cls: "bg-emerald-400/15 text-emerald-200" },
  building: {
    label: "building",
    cls: "bg-amber-400/15 text-amber-200 animate-pulse",
  },
  error: { label: "error", cls: "bg-rose-400/15 text-rose-200" },
};

export default function Workbench({
  topics,
  open,
  onToggle,
  highlightIds,
  renderCard,
}: {
  topics: Topic[];
  open: boolean;
  onToggle: () => void;
  /** Freshly-added ids — soft ring so the user can find them. */
  highlightIds?: Set<string>;
  renderCard: (t: Topic) => ReactNode;
}) {
  if (topics.length === 0) return null;

  const chips = PLAN_MODE.map((status) => ({
    status,
    n: topics.filter((t) => t.planStatus === status).length,
    ...STATUS_CHIP[status]!,
  })).filter((c) => c.n > 0);

  const live = topics.some(
    (t) => t.planStatus === "planning" || t.planStatus === "building"
  );

  return (
    <section
      className="workbench mt-6 overflow-hidden rounded-xl border border-[#f8d878]/20 bg-black/30 shadow-[0_8px_28px_rgba(0,0,0,0.35)]"
      aria-label="Workbench — cards still in plan mode"
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3 border-b border-white/[0.06] bg-gradient-to-r from-[#2a2418]/90 to-[#1a1e28]/90 px-4 py-3 text-left transition hover:from-[#322c1c] hover:to-[#1e2430]"
      >
        <span
          className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#f8d878]/15 text-sm ${
            live ? "animate-pulse" : ""
          }`}
          aria-hidden
        >
          ✎
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="font-display text-sm font-semibold tracking-tight text-[#f4ecd0]">
              Workbench
            </span>
            <span className="font-mono text-[11px] text-slate-500">
              {topics.length} in plan mode
              {live ? " · agent live" : ""}
            </span>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {chips.map((c) => (
              <span
                key={c.status}
                className={`rounded-full px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wide ${c.cls}`}
              >
                {c.n} {c.label}
              </span>
            ))}
          </div>
        </div>
        <span className="shrink-0 font-mono text-[11px] text-slate-500">
          {open ? "hide ▾" : "show ▸"}
        </span>
      </button>

      {open && (
        <div className="max-h-[min(52vh,520px)] space-y-2 overflow-y-auto p-3">
          <p className="mb-2 px-1 font-mono text-[10.5px] leading-relaxed text-slate-500">
            Cards that aren&apos;t built yet stay here so you can edit, plan, and
            approve without walking the map. Built concepts live on the island.
          </p>
          {topics.map((t) => (
            <div
              key={t.id}
              className={
                highlightIds?.has(t.id)
                  ? "rounded-xl ring-2 ring-[#f8d878]/50 ring-offset-2 ring-offset-[#0c1420] transition"
                  : undefined
              }
            >
              {renderCard(t)}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
