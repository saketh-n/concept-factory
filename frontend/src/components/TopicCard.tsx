import { useEffect, useRef, useState } from "react";
import { conceptUrl, type Topic } from "../api";

interface Props {
  topic: Topic;
  onChange: (patch: Partial<Omit<Topic, "id">>) => void;
  onDelete: () => void;
  onOpenPlan: () => void;
}

const PLAN_META: Record<
  Topic["planStatus"],
  { label: string; className: string; pulse?: boolean }
> = {
  none: { label: "", className: "" },
  queued: { label: "Queued", className: "bg-slate-100 text-slate-500" },
  planning: {
    label: "Planning…",
    className: "bg-indigo-50 text-indigo-600",
    pulse: true,
  },
  ready: { label: "Plan ready", className: "bg-emerald-50 text-emerald-700" },
  building: {
    label: "Building…",
    className: "bg-amber-50 text-amber-700",
    pulse: true,
  },
  built: { label: "Finished building", className: "bg-emerald-600 text-white" },
  error: { label: "Error", className: "bg-red-50 text-red-600" },
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
  const status = PLAN_META[topic.planStatus];
  const clickable = ["ready", "planning", "building", "built", "error"].includes(
    topic.planStatus
  );

  // Keep local edits in sync if the topic is replaced from the server.
  useEffect(() => setDraft(topic), [topic]);

  const commit = (field: keyof Omit<Topic, "id">) => {
    if (draft[field] !== topic[field]) onChange({ [field]: draft[field] });
  };

  return (
    <div className="group flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:shadow-md">
      <div className="flex items-start justify-between gap-2">
        <input
          className="w-full bg-transparent text-lg font-semibold text-slate-900 outline-none placeholder:text-slate-300"
          value={draft.title}
          placeholder="Untitled topic"
          onChange={(e) => setDraft({ ...draft, title: e.target.value })}
          onBlur={() => commit("title")}
        />
        <button
          onClick={onDelete}
          className="shrink-0 rounded-lg px-2 py-1 text-slate-300 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
          title="Delete topic"
        >
          ✕
        </button>
      </div>

      <AutoTextarea
        className="resize-none bg-transparent text-sm leading-relaxed text-slate-600 outline-none placeholder:text-slate-300"
        value={draft.blurb}
        placeholder="A brief blurb..."
        onChange={(e) => setDraft({ ...draft, blurb: e.target.value })}
        onBlur={() => commit("blurb")}
      />

      <div className="border-t border-slate-100 pt-3">
        <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-400">
          Notes
        </div>
        <AutoTextarea
          className="min-h-[4rem] w-full resize-none rounded-lg bg-slate-50 p-3 text-sm leading-relaxed text-slate-700 outline-none focus:ring-2 focus:ring-indigo-200 placeholder:text-slate-300"
          value={draft.notes}
          placeholder="Detailed notes go here..."
          onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
          onBlur={() => commit("notes")}
        />
      </div>

      {topic.planStatus !== "none" && (
        <div className={`flex items-center justify-between rounded-lg px-3 py-2 text-xs font-medium ${status.className}`}>
          <button
            onClick={clickable ? onOpenPlan : undefined}
            disabled={!clickable}
            className={`flex items-center gap-2 ${clickable ? "hover:opacity-80" : "cursor-default"}`}
          >
            {status.pulse && (
              <span className="h-2 w-2 animate-pulse rounded-full bg-current" />
            )}
            {status.label}
          </button>
          {topic.planStatus === "ready" && (
            <button onClick={onOpenPlan} className="hover:opacity-80">
              Review →
            </button>
          )}
          {(topic.planStatus === "planning" || topic.planStatus === "building") && (
            <button onClick={onOpenPlan} className="hover:opacity-80">
              Watch →
            </button>
          )}
          {topic.planStatus === "error" && (
            <button onClick={onOpenPlan} className="hover:opacity-80">
              Details →
            </button>
          )}
          {topic.planStatus === "built" && (
            <a
              href={conceptUrl(topic.slug)}
              target="_blank"
              rel="noreferrer"
              className="hover:opacity-80"
            >
              View Concept →
            </a>
          )}
        </div>
      )}
    </div>
  );
}
