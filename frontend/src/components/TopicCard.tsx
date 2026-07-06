import { useEffect, useRef, useState } from "react";
import { conceptUrl, type Topic } from "../api";
import FullstackControl from "./FullstackControl";

interface Props {
  topic: Topic;
  onChange: (patch: Partial<Omit<Topic, "id">>) => void;
  onDelete: () => void;
  onOpenPlan: () => void;
}

/** Lifecycle → color. In a control room, color means state, nothing else. */
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
    badge: "bg-slate-400/10 text-slate-300 ring-slate-400/20",
  },
  planning: {
    label: "Planning",
    rail: "bg-amber-400",
    badge: "bg-amber-400/10 text-amber-300 ring-amber-400/25",
    pulse: true,
  },
  ready: {
    label: "Plan ready",
    rail: "bg-violet-400",
    badge: "bg-violet-400/10 text-violet-300 ring-violet-400/25",
  },
  building: {
    label: "Building",
    rail: "bg-amber-400",
    badge: "bg-amber-400/10 text-amber-300 ring-amber-400/25",
    pulse: true,
  },
  built: {
    label: "Built",
    rail: "bg-emerald-400",
    badge: "bg-emerald-400/20 text-emerald-200 ring-emerald-400/40",
  },
  error: {
    label: "Error",
    rail: "bg-rose-400",
    badge: "bg-rose-400/10 text-rose-300 ring-rose-400/25",
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
}: Props) {
  const [draft, setDraft] = useState(topic);
  const [notesOpen, setNotesOpen] = useState(false);
  const status = PLAN_META[topic.planStatus];
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
      ? { label: "Review plan →", onClick: onOpenPlan }
      : topic.planStatus === "planning" || topic.planStatus === "building"
        ? { label: "Watch live →", onClick: onOpenPlan }
        : topic.planStatus === "error"
          ? { label: "See details →", onClick: onOpenPlan }
          : topic.planStatus === "built"
            ? {
                label: "Open concept →",
                onClick: () => window.open(conceptUrl(topic.slug), "_blank"),
              }
            : null;

  return (
    <div className="group relative overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.02] transition-colors hover:border-white/[0.14] hover:bg-white/[0.03]">
      {/* Signature: the status rail. Color = lifecycle state; pulses while a
          Claude Code instance is live on this topic. */}
      <span
        className={`absolute inset-y-0 left-0 w-[3px] ${status.rail} ${
          status.pulse ? "animate-pulse" : ""
        }`}
        aria-hidden
      />

      <div className="flex flex-col gap-2 py-3 pl-5 pr-4">
        {/* Row 1: title · status · action · delete */}
        <div className="flex items-center gap-3">
          <input
            className="min-w-0 flex-1 bg-transparent font-display text-[0.95rem] font-semibold text-slate-100 outline-none placeholder:text-slate-600"
            value={draft.title}
            placeholder="Untitled topic"
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            onBlur={() => commit("title")}
          />

          {status.label && (
            <button
              onClick={clickable ? onOpenPlan : undefined}
              disabled={!clickable}
              className={`shrink-0 rounded-full px-2.5 py-0.5 font-mono text-[10.5px] font-medium uppercase tracking-wide ring-1 ring-inset ${status.badge} ${
                clickable ? "cursor-pointer hover:brightness-125" : "cursor-default"
              }`}
            >
              {status.pulse && (
                <span className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current align-middle" />
              )}
              {status.label}
            </button>
          )}

          {action && (
            <button
              onClick={action.onClick}
              className="shrink-0 text-xs font-medium text-violet-300 transition-colors hover:text-violet-200"
            >
              {action.label}
            </button>
          )}

          <button
            onClick={onDelete}
            className="shrink-0 rounded-md px-1.5 py-0.5 text-slate-600 opacity-0 transition hover:bg-rose-400/10 hover:text-rose-300 focus-visible:opacity-100 group-hover:opacity-100"
            title="Delete topic"
          >
            ✕
          </button>
        </div>

        {/* Row 2: blurb (only takes space when present or focused) */}
        <AutoTextarea
          className="w-full resize-none bg-transparent text-[0.85rem] leading-relaxed text-slate-400 outline-none placeholder:text-transparent placeholder:transition-colors focus:placeholder:text-slate-600 group-hover:placeholder:text-slate-600"
          value={draft.blurb}
          placeholder="A brief blurb…"
          onChange={(e) => setDraft({ ...draft, blurb: e.target.value })}
          onBlur={() => commit("blurb")}
        />

        {/* Row 3: breadcrumb path · notes toggle */}
        <div className="flex items-center gap-3">
          <input
            className="min-w-0 flex-1 rounded-md bg-transparent px-0 font-mono text-[11px] text-slate-500 opacity-40 outline-none transition-opacity placeholder:text-transparent focus:opacity-100 focus:placeholder:text-slate-600 group-hover:opacity-100 group-hover:placeholder:text-slate-600"
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
              <span className="ml-1.5 inline-block h-1 w-1 rounded-full bg-violet-400/70 align-middle" />
            )}
          </button>
        </div>

        {/* Notes (disclosed) */}
        {notesOpen && (
          <AutoTextarea
            autoFocus
            className="min-h-[3.5rem] w-full resize-none rounded-lg border border-white/[0.06] bg-well p-3 text-[0.85rem] leading-relaxed text-slate-300 outline-none placeholder:text-slate-600"
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
