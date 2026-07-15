import type { ReactNode } from "react";
import type { Topic } from "../api";
import { IconChevronRight, IconClipboard } from "./icons";

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
  none: { label: "no plan", cls: "bg-white/[0.06] text-slate-300 ring-white/10" },
  queued: { label: "queued", cls: "bg-slate-400/10 text-slate-300 ring-slate-400/25" },
  planning: {
    label: "planning",
    cls: "bg-violet-400/10 text-violet-300 ring-violet-400/30 animate-pulse",
  },
  ready: { label: "plan ready", cls: "bg-sky-400/10 text-sky-300 ring-sky-400/30" },
  building: {
    label: "building",
    cls: "bg-amber-400/10 text-amber-300 ring-amber-400/30 animate-pulse",
  },
  error: { label: "error", cls: "bg-rose-400/10 text-rose-300 ring-rose-400/30" },
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
      className="workbench mt-5 overflow-hidden rounded-xl border border-white/[0.08] bg-panel shadow-card"
      aria-label="Workbench — cards still in plan mode"
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-white/[0.02]"
      >
        <span
          className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-sky-400/10 text-sky-300 ${
            live ? "animate-pulse" : ""
          }`}
          aria-hidden
        >
          <IconClipboard size={13} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-display text-[13.5px] font-semibold tracking-tight text-slate-100">
              Workbench
            </span>
            <span className="text-[11.5px] text-slate-500">
              {topics.length} in plan mode{live ? " · agent live" : ""}
            </span>
            <span className="flex flex-wrap gap-1.5">
              {chips.map((c) => (
                <span key={c.status} className={`badge ${c.cls}`}>
                  {c.n} {c.label}
                </span>
              ))}
            </span>
          </div>
        </div>
        <span
          className={`shrink-0 text-slate-500 transition-transform ${
            open ? "rotate-90" : ""
          }`}
          aria-hidden
        >
          <IconChevronRight size={14} />
        </span>
      </button>

      {open && (
        <div className="max-h-[min(52vh,520px)] space-y-2 overflow-y-auto border-t border-white/[0.06] p-3">
          {topics.map((t) => (
            <div
              key={t.id}
              className={
                highlightIds?.has(t.id)
                  ? "rounded-xl ring-2 ring-emerald-400/50 ring-offset-2 ring-offset-[#0a0e17] transition"
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
