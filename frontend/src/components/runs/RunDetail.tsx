import { useEffect, useState } from "react";
import {
  api,
  runExportUrl,
  type GateResult,
  type RunRecord,
} from "../../api";
import { IconDownload } from "../icons";
import { fmtCompact, fmtDur, fmtUsd } from "./format";

const gateGlyph: Record<string, string> = {
  pass: "✓",
  fail: "✗",
  error: "✗",
  skipped: "–",
};
const gateColor: Record<string, string> = {
  pass: "text-emerald-300",
  fail: "text-rose-300",
  error: "text-rose-300",
  skipped: "text-slate-500",
};

export function GateChip({ name, gate }: { name: string; gate?: GateResult }) {
  const status = gate?.status ?? "skipped";
  const extra =
    name === "validator" && gate?.total
      ? ` ${gate.passed}/${gate.total}`
      : "";
  return (
    <span
      title={`${name}: ${status}${gate?.detail ? ` — ${gate.detail}` : ""}`}
      className={`inline-flex items-center gap-1 rounded-md border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 text-[10.5px] ${gateColor[status] ?? "text-slate-500"}`}
    >
      {gateGlyph[status] ?? "–"} {name}
      {extra}
    </span>
  );
}

function summarizeEvent(evt: Record<string, unknown>): string {
  const type = String(evt.type ?? "event");
  if (type === "assistant") {
    const msg = evt.message as { content?: unknown } | undefined;
    const content = Array.isArray(msg?.content) ? msg?.content : [];
    const parts = content.map((b) => {
      const block = b as { type?: string; name?: string; text?: string };
      if (block.type === "tool_use") return `→ ${block.name}`;
      if (block.type === "text") return (block.text ?? "").slice(0, 80);
      if (block.type === "thinking") return "💭";
      return block.type ?? "";
    });
    return parts.filter(Boolean).join("  ") || "assistant message";
  }
  if (type === "result" || type === "end") {
    const cost = evt.total_cost_usd as number | undefined;
    const turns = evt.num_turns ?? "?";
    return `${type} — cost ${fmtUsd(cost)} · ${String(turns)} turns`;
  }
  if (type === "text" || type === "thought")
    return String(evt.data ?? "").slice(0, 100);
  const data = JSON.stringify(evt);
  return data.length > 100 ? data.slice(0, 100) + "…" : data;
}

export function RunDetail({ run }: { run: RunRecord }) {
  const [tab, setTab] = useState<"log" | "events" | "levels">("log");
  const [log, setLog] = useState<string[] | null>(null);
  const [events, setEvents] = useState<Record<string, unknown>[] | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (tab === "log" && log === null)
      api.getRunLog(run.id).then((r) => setLog(r.lines)).catch(() => setLog([]));
    if (tab === "events" && events === null)
      api
        .getRunEvents(run.id)
        .then((r) => setEvents(r.events))
        .catch(() => setEvents([]));
  }, [tab, run.id, log, events]);

  const validator = run.gates?.validator;
  const failedLevels = (validator?.levels ?? []).filter((l) => !l.ok);

  const meta: [string, string][] = [
    ["Driver", `${run.driverLabel || run.driver || "–"} · ${run.model || "default"}`],
    ["Started", run.startedAtIso ?? "–"],
    ["Duration", fmtDur(run.durationSeconds)],
    ["Cost", fmtUsd(run.costUsd)],
    [
      "Tokens",
      `${fmtCompact(run.tokensIn)} in · ${fmtCompact(run.tokensOut)} out · ${fmtCompact(run.cacheReadTokens)} cache`,
    ],
    ["Turns / tools", `${run.turns} turns · ${run.toolCalls} tool calls`],
    ["Retries", `${run.retries} (attempt${run.attempts === 1 ? "" : "s"}: ${run.attempts})`],
    ["Session", run.sessionId ? run.sessionId.slice(0, 18) : "–"],
    ["Exit code", run.exitCode == null ? "–" : String(run.exitCode)],
  ];

  return (
    <div className="border-t border-white/[0.06] bg-[#0c1017] px-4 py-4">
      <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3">
        {meta.map(([k, v]) => (
          <div key={k} className="text-[11.5px]">
            <span className="text-slate-500">{k}: </span>
            <span className="text-slate-300">{v}</span>
          </div>
        ))}
      </div>
      {run.error && (
        <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/[0.06] px-3 py-2 text-[12px] text-rose-200">
          {run.error}
        </div>
      )}

      <div className="mt-4 flex items-center gap-2">
        {(["log", "events", "levels"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-md px-2.5 py-1 text-[11.5px] font-medium capitalize transition-colors ${
              tab === t
                ? "bg-white/[0.08] text-slate-100"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {t === "levels"
              ? `levels${validator?.total ? ` (${validator.passed}/${validator.total})` : ""}`
              : t}
          </button>
        ))}
        <span className="ml-auto flex items-center gap-1.5">
          {(["json", "ndjson", "txt"] as const).map((f) => (
            <a
              key={f}
              href={runExportUrl(run.id, f)}
              download
              className="btn-ghost !px-2 !py-1 text-[11px] text-slate-400 hover:text-slate-200"
              title={
                f === "json"
                  ? "Full bundle: record + events + log"
                  : f === "ndjson"
                    ? "Raw event stream (replay in another tool)"
                    : "Readable log"
              }
            >
              <IconDownload size={11} /> {f}
            </a>
          ))}
        </span>
      </div>

      <div className="mt-2 max-h-72 overflow-auto rounded-lg border border-white/[0.06] bg-[#090c12] p-3 font-mono text-[11px] leading-relaxed text-slate-400">
        {tab === "log" &&
          (log === null ? (
            <span className="text-slate-600">loading…</span>
          ) : log.length === 0 ? (
            <span className="text-slate-600">log empty</span>
          ) : (
            log.map((line, i) => <div key={i}>{line}</div>)
          ))}
        {tab === "events" &&
          (events === null ? (
            <span className="text-slate-600">loading…</span>
          ) : events.length === 0 ? (
            <span className="text-slate-600">no events captured</span>
          ) : (
            events.map((evt, i) => (
              <div key={i} className="border-b border-white/[0.04] py-1 last:border-0">
                <button
                  className="flex w-full items-start gap-2 text-left"
                  onClick={() =>
                    setExpanded((prev) => {
                      const next = new Set(prev);
                      if (next.has(i)) next.delete(i);
                      else next.add(i);
                      return next;
                    })
                  }
                >
                  <span className="shrink-0 rounded bg-white/[0.06] px-1 text-[10px] text-slate-300">
                    {String(evt.type ?? "?")}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-slate-500">
                    {summarizeEvent(evt)}
                  </span>
                </button>
                {expanded.has(i) && (
                  <pre className="mt-1 overflow-auto whitespace-pre-wrap break-all text-[10px] text-slate-500">
                    {JSON.stringify(evt, null, 2)}
                  </pre>
                )}
              </div>
            ))
          ))}
        {tab === "levels" &&
          (!validator?.total ? (
            <span className="text-slate-600">
              validator {validator?.status ?? "skipped"}
              {validator?.detail ? ` — ${validator.detail}` : ""}
            </span>
          ) : (
            <div className="space-y-1">
              {(validator.levels ?? []).map((l) => (
                <div key={l.id} className="flex items-start gap-2">
                  <span className={l.ok ? "text-emerald-300" : "text-rose-300"}>
                    {l.ok ? "✓" : "✗"}
                  </span>
                  <span className="text-slate-400">
                    level {l.id}
                    {l.topic ? ` · ${l.topic}` : ""}
                  </span>
                  {!l.ok && <span className="text-slate-600">{l.reason}</span>}
                </div>
              ))}
              {failedLevels.length === 0 && (
                <div className="text-slate-600">all levels pass ✓</div>
              )}
            </div>
          ))}
      </div>
    </div>
  );
}

