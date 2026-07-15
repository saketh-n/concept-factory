import { useEffect, useRef, useState } from "react";
import { conceptUrl, type Topic } from "../api";
import FullstackControl from "./FullstackControl";
import { IconArrowRight, IconCheck, IconExternal, IconX } from "./icons";

interface Props {
  topic: Topic;
  onChange: (patch: Partial<Omit<Topic, "id">>) => void;
  onDelete: () => void;
  onOpenPlan: () => void;
  /** This card is currently selected for consolidation. */
  selected?: boolean;
  /** Toggle this card's selection. */
  onToggleSelect?: () => void;
  /** Playing the "collapse away into the merged card" animation. */
  merging?: boolean;
  /** The freshly-created consolidated card — plays an entrance animation. */
  entering?: boolean;
}

/** Lifecycle → color. Color always means state, nothing else. */
const PLAN_META: Record<
  Topic["planStatus"],
  { label: string; rail: string; badge: string; pulse?: boolean }
> = {
  none: {
    label: "",
    rail: "bg-white/10",
    badge: "",
  },
  queued: {
    label: "Queued",
    rail: "bg-slate-400/70",
    badge: "bg-slate-400/10 text-slate-300 ring-slate-400/25",
  },
  planning: {
    label: "Planning",
    rail: "bg-violet-400",
    badge: "bg-violet-400/10 text-violet-300 ring-violet-400/30",
    pulse: true,
  },
  ready: {
    label: "Plan ready",
    rail: "bg-sky-400",
    badge: "bg-sky-400/10 text-sky-300 ring-sky-400/30",
  },
  building: {
    label: "Building",
    rail: "bg-amber-400",
    badge: "bg-amber-400/10 text-amber-300 ring-amber-400/30",
    pulse: true,
  },
  built: {
    label: "Built",
    rail: "bg-emerald-400",
    badge: "bg-emerald-400/15 text-emerald-300 ring-emerald-400/35",
  },
  error: {
    label: "Error",
    rail: "bg-rose-400",
    badge: "bg-rose-400/10 text-rose-300 ring-rose-400/30",
  },
};

/** Textarea that grows to fit its content. */
function AutoTextarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const resize = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  };
  useEffect(resize, [props.value]);
  return <textarea ref={ref} rows={1} onInput={resize} {...props} />;
}

export default function TopicCard({
  topic,
  onChange,
  onDelete,
  onOpenPlan,
  selected = false,
  onToggleSelect,
  merging = false,
  entering = false,
}: Props) {
  const [draft, setDraft] = useState(topic);
  const [notesOpen, setNotesOpen] = useState(false);
  const status = PLAN_META[topic.planStatus];
  const built = topic.planStatus === "built";
  // Only plan-ready cards can be folded into a consolidated plan.
  const selectable = topic.planStatus === "ready";

  // Once built, the card carries a second axis — review state — as a whole-card
  // tint: amber until a human signs off, quiet emerald once reviewed.
  const cardTint = built
    ? topic.reviewed
      ? "border-white/[0.07] bg-panel hover:border-white/[0.13]"
      : "border-amber-400/25 bg-amber-400/[0.03] hover:border-amber-400/40"
    : "border-white/[0.07] bg-panel hover:border-white/[0.13]";
  const clickable = ["ready", "planning", "building", "built", "error"].includes(
    topic.planStatus
  );

  // Path edited as breadcrumb text ("Linux > Shell"); parsed on blur.
  const [pathText, setPathText] = useState((topic.path ?? []).join(" > "));
  useEffect(() => setPathText((topic.path ?? []).join(" > ")), [topic.path]);
  const commitPath = () => {
    const parsed = pathText
      .split(">")
      .map((p) => p.trim())
      .filter(Boolean);
    if (parsed.join(" > ") !== (topic.path ?? []).join(" > "))
      onChange({ path: parsed });
  };

  // Keep local edits in sync if the topic is replaced from the server.
  useEffect(() => setDraft(topic), [topic]);

  const commit = (field: keyof Omit<Topic, "id">) => {
    if (draft[field] !== topic[field]) onChange({ [field]: draft[field] });
  };

  const action =
    topic.planStatus === "ready"
      ? { label: "Review plan", onClick: onOpenPlan, external: false }
      : topic.planStatus === "planning" || topic.planStatus === "building"
        ? { label: "Watch live", onClick: onOpenPlan, external: false }
        : topic.planStatus === "error"
          ? { label: "See details", onClick: onOpenPlan, external: false }
          : topic.planStatus === "built"
            ? {
                label: "Open concept",
                onClick: () => window.open(conceptUrl(topic.slug), "_blank"),
                external: true,
              }
            : null;

  return (
    <div
      className={`group relative overflow-hidden rounded-xl border shadow-card transition-colors ${cardTint} ${
        selected ? "ring-2 ring-inset ring-violet-400/60" : ""
      } ${merging ? "merge-out" : ""} ${entering ? "merge-in" : ""}`}
    >
      {/* Signature: the status rail. Color = lifecycle state; pulses while an
          agent is live on this topic. */}
      <span
        className={`absolute inset-y-0 left-0 w-[3px] ${status.rail} ${
          status.pulse ? "animate-pulse" : ""
        }`}
        aria-hidden
      />

      <div className="flex flex-col gap-1.5 py-3 pl-5 pr-4">
        {/* Row 1: [select] title · status · action · delete */}
        <div className="flex items-center gap-3">
          {selectable && onToggleSelect && (
            <input
              type="checkbox"
              checked={selected}
              onChange={onToggleSelect}
              title="Select to consolidate this plan with others"
              className="h-4 w-4 shrink-0 cursor-pointer accent-violet-400"
            />
          )}
          <input
            className="min-w-0 flex-1 bg-transparent text-[14.5px] font-semibold tracking-tight text-slate-100 outline-none placeholder:text-slate-600"
            value={draft.title}
            placeholder="Untitled topic"
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            onBlur={() => commit("title")}
          />

          {status.label && (
            <button
              onClick={clickable ? onOpenPlan : undefined}
              disabled={!clickable}
              className={`badge ${status.badge} ${
                clickable ? "cursor-pointer hover:brightness-125" : "cursor-default"
              }`}
            >
              {status.pulse && (
                <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
              )}
              {status.label}
            </button>
          )}

          {built && (
            <button
              onClick={() => onChange({ reviewed: !topic.reviewed })}
              className={`badge transition ${
                topic.reviewed
                  ? "bg-emerald-400/10 text-emerald-300/90 ring-emerald-400/25 hover:brightness-110"
                  : "bg-amber-400/10 text-amber-300 ring-amber-400/30 hover:bg-amber-400/20"
              }`}
              title={
                topic.reviewed
                  ? "Reviewed — click to unmark"
                  : "Not yet reviewed — click to mark reviewed"
              }
            >
              {topic.reviewed ? (
                <>
                  <IconCheck size={10} /> Reviewed
                </>
              ) : (
                "Needs review"
              )}
            </button>
          )}

          {action && (
            <button
              onClick={action.onClick}
              className="flex shrink-0 items-center gap-1 text-[12.5px] font-medium text-emerald-300/90 transition-colors hover:text-emerald-200"
            >
              {action.label}
              {action.external ? (
                <IconExternal size={11} />
              ) : (
                <IconArrowRight size={11} />
              )}
            </button>
          )}

          <button
            onClick={onDelete}
            className="shrink-0 rounded-md p-1 text-slate-600 opacity-0 transition hover:bg-rose-400/10 hover:text-rose-300 focus-visible:opacity-100 group-hover:opacity-100"
            title="Delete topic"
          >
            <IconX size={12} />
          </button>
        </div>

        {/* Row 2: blurb — collapsed entirely until it has content, hover, or focus */}
        <AutoTextarea
          className={`${
            draft.blurb.trim()
              ? ""
              : "hidden group-focus-within:block group-hover:block"
          } w-full resize-none bg-transparent text-[13px] leading-relaxed text-slate-400 outline-none placeholder:text-transparent placeholder:transition-colors focus:placeholder:text-slate-600 group-hover:placeholder:text-slate-600`}
          value={draft.blurb}
          placeholder="A brief blurb…"
          onChange={(e) => setDraft({ ...draft, blurb: e.target.value })}
          onBlur={() => commit("blurb")}
        />

        {/* Row 3: breadcrumb path · notes toggle */}
        <div className="flex items-center gap-3">
          <input
            className="min-w-0 flex-1 rounded-md bg-transparent px-0 font-mono text-[11px] text-slate-500 opacity-50 outline-none transition-opacity placeholder:text-transparent focus:opacity-100 focus:placeholder:text-slate-600 group-hover:opacity-100 group-hover:placeholder:text-slate-600"
            value={pathText}
            placeholder="Group > Subgroup — type to move this card"
            title="Hierarchy path — edit to move this card to another group"
            onChange={(e) => setPathText(e.target.value)}
            onBlur={commitPath}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            }}
          />

          <button
            onClick={() => setNotesOpen((o) => !o)}
            className="shrink-0 font-mono text-[11px] text-slate-500 opacity-60 transition-opacity hover:text-slate-300 hover:opacity-100 group-hover:opacity-100"
          >
            <span
              className={`mr-1 inline-block transition-transform ${
                notesOpen ? "rotate-90" : ""
              }`}
            >
              ▸
            </span>
            notes
            {topic.notes.trim() && (
              <span className="ml-1.5 inline-block h-1 w-1 rounded-full bg-emerald-400/80 align-middle" />
            )}
          </button>
        </div>

        {/* Notes (disclosed) */}
        {notesOpen && (
          <AutoTextarea
            autoFocus
            className="field min-h-[3.5rem] w-full resize-none text-[13px] leading-relaxed"
            value={draft.notes}
            placeholder="Notes for the agent — angle, gotchas, what to emphasize…"
            onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
            onBlur={() => commit("notes")}
          />
        )}

        {topic.fullstack && <FullstackControl slug={topic.slug} />}
      </div>
    </div>
  );
}
