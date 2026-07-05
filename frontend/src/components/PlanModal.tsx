import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, conceptUrl, type Topic } from "../api";

interface Props {
  topic: Topic;
  onSaved: (t: Topic) => void;
  onClose: () => void;
}

const BUSY: Topic["planStatus"][] = ["queued", "planning", "building"];

/** Live-streamed progress from the running Claude Code instance. */
function StreamLog({ topicId }: { topicId: string }) {
  const [lines, setLines] = useState<string[]>([]);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const { lines } = await api.getLog(topicId);
        if (alive) setLines(lines);
      } catch {
        /* ignore transient poll errors */
      }
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [topicId]);

  // Keep the newest output in view.
  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight });
  }, [lines]);

  return (
    <div
      ref={boxRef}
      className="h-[52vh] overflow-y-auto rounded-lg bg-[#0e1017] p-4 font-mono text-[0.8rem] leading-relaxed text-slate-300"
    >
      {lines.length === 0 ? (
        <span className="text-slate-500">Waiting for Claude Code…</span>
      ) : (
        lines.map((l, i) => (
          <div key={i} className="whitespace-pre-wrap break-words">
            {l}
          </div>
        ))
      )}
      <div className="mt-1 inline-block h-3 w-2 animate-pulse bg-emerald-400/70" />
    </div>
  );
}

export default function PlanModal({ topic, onSaved, onClose }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(topic.plan);
  const [refine, setRefine] = useState("");
  const [saving, setSaving] = useState(false);

  const busy = BUSY.includes(topic.planStatus);
  const built = topic.planStatus === "built";

  useEffect(() => {
    if (!editing) setDraft(topic.plan);
  }, [topic.plan, editing]);

  const save = async () => {
    setSaving(true);
    try {
      onSaved(await api.savePlan(topic.id, draft));
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const sendRefine = async () => {
    if (!refine.trim()) return;
    onSaved(await api.refinePlan(topic.id, refine.trim()));
    setRefine("");
  };

  const build = async () => onSaved(await api.buildTopic(topic.id));
  const viewConcept = () => window.open(conceptUrl(topic.slug), "_blank");

  const heading = busy
    ? topic.planStatus === "building"
      ? "Building…"
      : "Planning…"
    : built
      ? "Finished building"
      : "Plan review";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold text-slate-900">
              {topic.title}
            </h2>
            <p className="text-xs text-slate-400">
              {heading} · workspace/{topic.slug}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {topic.plan && !busy && !editing && (
              <button
                onClick={() => setEditing(true)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
              >
                Edit
              </button>
            )}
            {editing && (
              <button
                onClick={() => setEditing(false)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
              >
                Preview
              </button>
            )}
            <button
              onClick={onClose}
              className="rounded-lg px-2 py-1.5 text-slate-400 hover:bg-slate-100"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {busy ? (
            <StreamLog topicId={topic.id} />
          ) : topic.planStatus === "error" ? (
            <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700">
              <div className="mb-1 font-medium">Something went wrong</div>
              {topic.planError || "Unknown error"}
            </div>
          ) : editing ? (
            <textarea
              className="h-[52vh] w-full resize-none rounded-lg border border-slate-200 bg-slate-50 p-4 font-mono text-sm text-slate-800 outline-none focus:ring-2 focus:ring-indigo-200"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
          ) : built ? (
            <div className="space-y-4">
              <div className="rounded-lg bg-emerald-50 p-4 text-sm text-emerald-800">
                Claude Code finished building the concept. Open it to explore the
                Learn guide and Test game.
              </div>
              {topic.plan && (
                <details className="text-sm">
                  <summary className="cursor-pointer text-slate-500">
                    Show the plan it was built from
                  </summary>
                  <div className="plan-prose mt-3">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {topic.plan}
                    </ReactMarkdown>
                  </div>
                </details>
              )}
            </div>
          ) : topic.plan ? (
            <div className="plan-prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {topic.plan}
              </ReactMarkdown>
            </div>
          ) : (
            <p className="text-sm text-slate-400">No plan yet.</p>
          )}
        </div>

        {/* Footer */}
        {built ? (
          <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50 px-6 py-4">
            <span className="text-sm font-medium text-emerald-700">
              ✓ Finished building
            </span>
            <button
              onClick={viewConcept}
              className="rounded-lg bg-emerald-600 px-5 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-emerald-700 active:scale-95"
            >
              View Concept →
            </button>
          </div>
        ) : !busy && topic.plan ? (
          <div className="space-y-3 border-t border-slate-200 bg-slate-50 px-6 py-4">
            <div className="flex gap-2">
              <input
                className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-200"
                placeholder="Ask Claude Code to refine the plan…"
                value={refine}
                onChange={(e) => setRefine(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendRefine()}
              />
              <button
                onClick={sendRefine}
                disabled={!refine.trim()}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-white disabled:opacity-40"
              >
                Refine
              </button>
            </div>
            <div className="flex items-center justify-between">
              {editing ? (
                <button
                  onClick={save}
                  disabled={saving}
                  className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-900 disabled:opacity-50"
                >
                  {saving ? "Saving…" : "Save edits"}
                </button>
              ) : (
                <span className="text-xs text-slate-400">
                  Edit manually, refine with a prompt, or approve to build.
                </span>
              )}
              <button
                onClick={build}
                className="rounded-lg bg-emerald-600 px-5 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-emerald-700 active:scale-95"
              >
                Approve & build
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
