import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, conceptUrl, type Commit, type Topic } from "../api";

function relTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const s = Math.round((Date.now() - then) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/** Improve-this-app box + git version history with revert. Also available as a
 *  floating bubble on the concept page itself — both drive the same endpoints. */
function BuiltPanel({
  topic,
  onSaved,
}: {
  topic: Topic;
  onSaved: (t: Topic) => void;
}) {
  const [commits, setCommits] = useState<Commit[]>([]);
  const [request, setRequest] = useState("");

  const loadHistory = () =>
    api.getHistory(topic.id).then((r) => setCommits(r.commits)).catch(() => {});

  // (Re)load history whenever the app settles back into "built".
  useEffect(() => {
    if (topic.planStatus === "built") loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topic.id, topic.planStatus]);

  const improve = async () => {
    if (!request.trim()) return;
    onSaved(await api.improveApp(topic.id, request.trim()));
    setRequest("");
  };

  const revert = async (hash: string) => {
    if (!confirm("Revert the app to this version? A new commit will record it.")) return;
    onSaved(await api.revertTo(topic.id, hash));
  };

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-emerald-400/20 bg-emerald-400/10 p-4 text-sm text-emerald-200">
        Grok finished building the concept. Open it, request improvements,
        or roll back to an earlier version below.
      </div>

      {/* Request an improvement */}
      <div>
        <div className="mb-1.5 font-mono text-[11px] uppercase tracking-[0.15em] text-slate-500">
          Improve this app
        </div>
        <div className="flex gap-2">
          <input
            className="flex-1 rounded-lg border border-white/10 bg-ink px-3 py-2 text-sm text-slate-200 outline-none placeholder:text-slate-600 focus:border-violet-400/40"
            placeholder="e.g. add a dark-mode toggle, or two harder levels…"
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && improve()}
          />
          <button
            onClick={improve}
            disabled={!request.trim()}
            className="rounded-lg bg-violet-400/15 px-4 py-2 text-sm font-medium text-violet-200 ring-1 ring-inset ring-violet-400/30 hover:bg-violet-400/25 disabled:opacity-40"
          >
            Improve
          </button>
        </div>
      </div>

      {/* Version history */}
      <div>
        <div className="mb-1.5 font-mono text-[11px] uppercase tracking-[0.15em] text-slate-500">
          Version history
        </div>
        {commits.length === 0 ? (
          <p className="text-sm text-slate-500">No commits yet.</p>
        ) : (
          <ol className="divide-y divide-white/[0.06] rounded-lg border border-white/10">
            {commits.map((c, i) => (
              <li key={c.hash} className="flex items-center justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <div className="truncate text-sm text-slate-300">{c.message}</div>
                  <div className="font-mono text-xs text-slate-500">
                    {c.hash.slice(0, 7)} · {relTime(c.date)}
                  </div>
                </div>
                {i === 0 ? (
                  <span className="shrink-0 rounded-full bg-emerald-400/15 px-2 py-0.5 font-mono text-[11px] font-medium text-emerald-300 ring-1 ring-inset ring-emerald-400/30">
                    current
                  </span>
                ) : (
                  <button
                    onClick={() => revert(c.hash)}
                    className="shrink-0 rounded-lg border border-white/10 px-2.5 py-1 text-xs font-medium text-slate-400 hover:bg-white/[0.05] hover:text-slate-200"
                  >
                    Revert
                  </button>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

interface Props {
  topic: Topic;
  onSaved: (t: Topic) => void;
  onClose: () => void;
}

const BUSY: Topic["planStatus"][] = ["queued", "planning", "building"];

/** Live-streamed progress from the running Grok instance. */
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
      className="h-[52vh] overflow-y-auto rounded-lg border border-white/[0.06] bg-ink p-4 font-mono text-[0.8rem] leading-relaxed text-slate-300"
    >
      {lines.length === 0 ? (
        <span className="text-slate-500">Waiting for Grok…</span>
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0e1117] shadow-2xl shadow-black/60"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.07] px-6 py-4">
          <div className="min-w-0">
            <h2 className="truncate font-display text-lg font-semibold text-slate-100">
              {topic.title}
            </h2>
            <p className="font-mono text-[11px] text-slate-500">
              {heading} · workspace/{topic.slug}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {topic.plan && !busy && !editing && (
              <button
                onClick={() => setEditing(true)}
                className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-slate-300 hover:bg-white/[0.05]"
              >
                Edit
              </button>
            )}
            {editing && (
              <button
                onClick={() => setEditing(false)}
                className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-slate-300 hover:bg-white/[0.05]"
              >
                Preview
              </button>
            )}
            <button
              onClick={onClose}
              className="rounded-lg px-2 py-1.5 text-slate-500 hover:bg-white/[0.06] hover:text-slate-300"
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
            <div className="rounded-lg border border-rose-400/20 bg-rose-400/10 p-4 text-sm text-rose-200">
              <div className="mb-1 font-medium">Something went wrong</div>
              {topic.planError || "Unknown error"}
            </div>
          ) : editing ? (
            <textarea
              className="h-[52vh] w-full resize-none rounded-lg border border-white/10 bg-ink p-4 font-mono text-sm text-slate-200 outline-none focus:border-violet-400/40"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
          ) : built ? (
            <BuiltPanel topic={topic} onSaved={onSaved} />
          ) : topic.plan ? (
            <div className="plan-prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {topic.plan}
              </ReactMarkdown>
            </div>
          ) : (
            <p className="text-sm text-slate-500">No plan yet.</p>
          )}
        </div>

        {/* Footer */}
        {built ? (
          <div className="flex items-center justify-between border-t border-white/[0.07] bg-white/[0.02] px-6 py-4">
            <span className="text-sm font-medium text-emerald-300">
              ✓ Finished building
            </span>
            <button
              onClick={viewConcept}
              className="rounded-full bg-emerald-400/15 px-5 py-2 text-sm font-medium text-emerald-200 ring-1 ring-inset ring-emerald-400/40 transition hover:bg-emerald-400/25 active:scale-95"
            >
              View Concept →
            </button>
          </div>
        ) : !busy && topic.plan ? (
          <div className="space-y-3 border-t border-white/[0.07] bg-white/[0.02] px-6 py-4">
            <div className="flex gap-2">
              <input
                className="flex-1 rounded-lg border border-white/10 bg-ink px-3 py-2 text-sm text-slate-200 outline-none placeholder:text-slate-600 focus:border-violet-400/40"
                placeholder="Ask Grok to refine the plan…"
                value={refine}
                onChange={(e) => setRefine(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendRefine()}
              />
              <button
                onClick={sendRefine}
                disabled={!refine.trim()}
                className="rounded-lg border border-white/10 px-4 py-2 text-sm font-medium text-slate-300 hover:bg-white/[0.05] disabled:opacity-40"
              >
                Refine
              </button>
            </div>
            <div className="flex items-center justify-between">
              {editing ? (
                <button
                  onClick={save}
                  disabled={saving}
                  className="rounded-lg bg-violet-400/15 px-4 py-2 text-sm font-medium text-violet-200 ring-1 ring-inset ring-violet-400/30 hover:bg-violet-400/25 disabled:opacity-50"
                >
                  {saving ? "Saving…" : "Save edits"}
                </button>
              ) : (
                <span className="text-xs text-slate-500">
                  Edit manually, refine with a prompt, or approve to build.
                </span>
              )}
              <button
                onClick={build}
                className="rounded-full bg-emerald-400/15 px-5 py-2 text-sm font-medium text-emerald-200 ring-1 ring-inset ring-emerald-400/40 transition hover:bg-emerald-400/25 active:scale-95"
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
