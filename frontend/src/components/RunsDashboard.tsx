import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  runExportUrl,
  type GateResult,
  type RunMetrics,
  type RunRecord,
} from "../api";
import { filterRuns, metricsFromRuns } from "../runMetrics";
import { usePolling } from "../hooks/usePolling";
import { IconDownload, IconSearch, IconX } from "./icons";

/**
 * Runs & metrics dashboard: every agent run (plan / refine / consolidate /
 * build / improve) is persisted server-side with structured metrics — this
 * view charts them and drills into any run's full log + raw event stream.
 *
 * Chart colors are validated for CVD + contrast against the #10151f panel:
 * series-1 blue / series-2 green for identity, status colors strictly for
 * pass/fail and always paired with a ✓/✗/– glyph, never color alone.
 */
const SERIES_1 = "#3987e5"; // blue — single-series magnitude, token input
const SERIES_2 = "#008300"; // green — token output
const STATUS_GOOD = "#0ca30c";
const STATUS_BAD = "#d03b3b";
const STATUS_SKIP = "#898781";
const GRID = "rgba(255,255,255,0.06)";
const BASELINE = "rgba(255,255,255,0.16)";

const KINDS = ["plan", "refine", "consolidate", "build", "improve"] as const;

// --- formatting ---------------------------------------------------------------
const fmtCompact = (n: number): string => {
  if (!isFinite(n)) return "–";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
  return `${Math.round(n)}`;
};

const fmtUsd = (n: number | null | undefined): string => {
  if (n == null) return "–";
  if (n !== 0 && Math.abs(n) < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
};

const fmtDur = (s: number | null | undefined): string => {
  if (s == null) return "–";
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${Math.round(s % 60)}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
};

const fmtClock = (ts: number): string =>
  new Date(ts * 1000).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

// --- tiny layout helpers --------------------------------------------------------
/** Measured width of a container so SVG charts render crisp at any size. */
function useMeasure<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setW(e.contentRect.width);
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** ~3 clean axis ticks covering [0, max]. */
function niceTicks(max: number): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / 2.5;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? 10 * pow;
  const ticks: number[] = [];
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(v);
  if (ticks[ticks.length - 1] < max) ticks.push(ticks.length * step);
  return ticks;
}

/** Bar with a 4px rounded data-end, square at the baseline. */
function barPath(x: number, yTop: number, w: number, h: number): string {
  if (h <= 0) return "";
  const r = Math.min(4, w / 2, h);
  return [
    `M${x},${yTop + h}`,
    `v${-(h - r)}`,
    `q0,${-r} ${r},${-r}`,
    `h${w - 2 * r}`,
    `q${r},0 ${r},${r}`,
    `v${h - r}`,
    "z",
  ].join("");
}

// --- charts ---------------------------------------------------------------------
interface BarPoint {
  key: string;
  value: number;
  /** Second (stacked) segment value, drawn above `value` with a 2px gap. */
  value2?: number;
  tooltip: string[];
}

/** Vertical bar chart (single series, or stacked pair when value2 is set). */
function Bars({
  points,
  yFmt,
  height = 148,
  stackedLabels,
}: {
  points: BarPoint[];
  yFmt: (v: number) => string;
  height?: number;
  /** Legend labels [series1, series2] — only for the stacked variant. */
  stackedLabels?: [string, string];
}) {
  const [wrapRef, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const PAD_L = 40;
  const PAD_B = 18;
  const PAD_T = 8;
  const plotW = Math.max(0, width - PAD_L - 6);
  const plotH = height - PAD_B - PAD_T;
  const max = Math.max(1e-9, ...points.map((p) => p.value + (p.value2 ?? 0)));
  const ticks = niceTicks(max);
  const yMax = ticks[ticks.length - 1];
  const band = points.length ? plotW / points.length : plotW;
  const barW = Math.max(2, Math.min(24, band - 2));
  const y = (v: number) => PAD_T + plotH * (1 - v / yMax);

  return (
    <div ref={wrapRef} className="relative">
      {stackedLabels && (
        <div className="mb-1.5 flex items-center gap-4 text-[11px] text-slate-400">
          {[SERIES_1, SERIES_2].map((c, i) => (
            <span key={c} className="flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-[3px]"
                style={{ background: c }}
              />
              {stackedLabels[i]}
            </span>
          ))}
        </div>
      )}
      {width > 0 && (
        <svg width={width} height={height} role="img">
          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={PAD_L}
                x2={width - 4}
                y1={y(t)}
                y2={y(t)}
                stroke={t === 0 ? BASELINE : GRID}
                strokeWidth={1}
              />
              <text
                x={PAD_L - 6}
                y={y(t) + 3}
                textAnchor="end"
                fontSize={9.5}
                fill="#898781"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {yFmt(t)}
              </text>
            </g>
          ))}
          {points.map((p, i) => {
            const x = PAD_L + i * band + (band - barW) / 2;
            const h1 = (p.value / yMax) * plotH;
            const h2 = ((p.value2 ?? 0) / yMax) * plotH;
            return (
              <g key={p.key} opacity={hover === null || hover === i ? 1 : 0.45}>
                <path d={barPath(x, y(p.value), barW, h1)} fill={SERIES_1} />
                {h2 > 0.5 && (
                  // stacked segment, separated by a 2px surface gap
                  <path
                    d={barPath(x, y(p.value + (p.value2 ?? 0)) - 2, barW, h2)}
                    fill={SERIES_2}
                  />
                )}
                <rect
                  x={PAD_L + i * band}
                  y={PAD_T}
                  width={band}
                  height={plotH + PAD_B}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                />
              </g>
            );
          })}
          {points.length > 0 && (
            <>
              <text x={PAD_L} y={height - 4} fontSize={9.5} fill="#898781">
                oldest
              </text>
              <text
                x={width - 4}
                y={height - 4}
                textAnchor="end"
                fontSize={9.5}
                fill="#898781"
              >
                latest
              </text>
            </>
          )}
        </svg>
      )}
      {hover !== null && points[hover] && width > 0 && (
        <div
          className="pointer-events-none absolute z-10 rounded-lg border border-white/10 bg-[#0c1017] px-2.5 py-1.5 text-[11px] leading-relaxed text-slate-300 shadow-pop"
          style={{
            left: Math.min(
              Math.max(0, PAD_L + hover * band - 40),
              Math.max(0, width - 170)
            ),
            top: -6,
            transform: "translateY(-100%)",
          }}
        >
          {points[hover].tooltip.map((line, i) => (
            <div key={i} className={i === 0 ? "font-medium text-slate-100" : ""}>
              {line}
            </div>
          ))}
        </div>
      )}
      {points.length === 0 && (
        <div
          className="grid place-items-center text-[12px] text-slate-600"
          style={{ height }}
        >
          no data yet
        </div>
      )}
    </div>
  );
}

/** One horizontal pass/fail/skipped band per gate — counts always labeled. */
function GateOutcomes({ metrics }: { metrics: RunMetrics }) {
  const rows = (["lint", "build", "validator"] as const).map((name) => ({
    name,
    ...metrics.gates[name],
  }));
  return (
    <div className="space-y-3">
      {rows.map((r) => {
        const total = r.pass + r.fail + r.skipped;
        const seg = (n: number) => (total ? (n / total) * 100 : 0);
        return (
          <div key={r.name}>
            <div className="mb-1 flex items-baseline justify-between text-[11.5px]">
              <span className="font-medium capitalize text-slate-300">
                {r.name}
              </span>
              <span className="text-slate-500" style={{ fontVariantNumeric: "tabular-nums" }}>
                ✓ {r.pass} pass · ✗ {r.fail} fail · – {r.skipped} skipped
              </span>
            </div>
            <div className="flex h-3 w-full gap-[2px] overflow-hidden rounded-full">
              {total === 0 ? (
                <div className="h-full w-full bg-white/[0.04]" />
              ) : (
                <>
                  {r.pass > 0 && (
                    <div style={{ width: `${seg(r.pass)}%`, background: STATUS_GOOD }} />
                  )}
                  {r.fail > 0 && (
                    <div style={{ width: `${seg(r.fail)}%`, background: STATUS_BAD }} />
                  )}
                  {r.skipped > 0 && (
                    <div style={{ width: `${seg(r.skipped)}%`, background: STATUS_SKIP, opacity: 0.55 }} />
                  )}
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StatTile({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-white/[0.08] bg-panel px-4 py-3 shadow-card">
      <div className="text-[11px] font-medium text-slate-500">{label}</div>
      <div className="mt-0.5 font-display text-[22px] font-semibold leading-tight text-slate-100">
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-slate-500">{sub}</div>}
    </div>
  );
}

// --- run detail (log / events / levels + export) ---------------------------------
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

function GateChip({ name, gate }: { name: string; gate?: GateResult }) {
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

function RunDetail({ run }: { run: RunRecord }) {
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

// --- main view --------------------------------------------------------------------
export default function RunsDashboard() {
  const [runs, setRuns] = useState<RunRecord[] | null>(null);
  const [kind, setKind] = useState<string>("");
  const [query, setQuery] = useState("");
  /** Explicit individual-run focus for metrics (not just table search). */
  const [runId, setRunId] = useState<string>("");
  const [openId, setOpenId] = useState<string | null>(null);

  const anyRunning = (runs ?? []).some((r) => r.status === "running");

  usePolling(
    async () => {
      try {
        const r = await api.listRuns({ limit: 500 });
        setRuns(r.runs);
      } catch {
        setRuns((prev) => prev ?? []);
      }
    },
    anyRunning ? 2500 : 6000,
    { immediate: true }
  );

  // Drop a selected run id if it disappeared (or is filtered out by kind).
  useEffect(() => {
    if (!runId || !runs) return;
    if (!runs.some((r) => r.id === runId)) setRunId("");
  }, [runs, runId]);

  // Kind + text + individual run — one filter row scopes tiles, charts, table.
  const filtered = useMemo(
    () => filterRuns(runs ?? [], { kind, query, runId }),
    [runs, kind, query, runId]
  );

  // KPIs always match the filtered selection (one run when selected).
  const m: RunMetrics | null = useMemo(
    () => (runs === null ? null : metricsFromRuns(filtered)),
    [runs, filtered]
  );

  // Options for the run picker: respect kind/query so the list stays useful.
  const runOptions = useMemo(
    () => filterRuns(runs ?? [], { kind, query }),
    [runs, kind, query]
  );

  // Charts read the last 30 filtered runs, oldest → newest.
  const chartRuns = useMemo(
    () => [...filtered].slice(0, 30).reverse(),
    [filtered]
  );

  const runLabel = (r: RunRecord) =>
    `${r.title || r.slug || r.id} · ${r.kind} · ${fmtClock(r.startedAt)}`;

  const costPoints: BarPoint[] = chartRuns.map((r) => ({
    key: r.id,
    value: r.costUsd ?? 0,
    tooltip: [runLabel(r), `cost ${fmtUsd(r.costUsd)}`],
  }));
  const durPoints: BarPoint[] = chartRuns.map((r) => ({
    key: r.id,
    value: r.durationSeconds ?? 0,
    tooltip: [runLabel(r), `duration ${fmtDur(r.durationSeconds)}`],
  }));
  const tokenPoints: BarPoint[] = chartRuns.map((r) => ({
    key: r.id,
    value: r.tokensIn,
    value2: r.tokensOut,
    tooltip: [
      runLabel(r),
      `in ${fmtCompact(r.tokensIn)} · out ${fmtCompact(r.tokensOut)}`,
      `cache read ${fmtCompact(r.cacheReadTokens)}`,
    ],
  }));
  const passPoints: BarPoint[] = chartRuns
    .filter((r) => (r.gates?.validator?.total ?? 0) > 0)
    .map((r) => ({
      key: r.id,
      value: (r.gates.validator.passRate ?? 0) * 100,
      tooltip: [
        runLabel(r),
        `levels ${r.gates.validator.passed}/${r.gates.validator.total} pass`,
      ],
    }));

  const costSub =
    runId
      ? "selected run"
      : kind || query
        ? "filtered runs"
        : "all instrumented runs";

  return (
    <div className="space-y-5">
      {/* Filter row — scopes every chart and the table below it. */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="view-toggle" role="group" aria-label="Run kind">
          <button
            type="button"
            onClick={() => setKind("")}
            className={kind === "" ? "is-active" : ""}
            aria-pressed={kind === ""}
          >
            All
          </button>
          {KINDS.map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setKind(kind === k ? "" : k)}
              className={kind === k ? "is-active" : ""}
              aria-pressed={kind === k}
            >
              {k}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1.5 text-[11.5px] text-slate-500">
          <span className="sr-only">Individual run</span>
          <select
            className="field max-w-[260px] py-1.5 text-[12.5px]"
            aria-label="Filter metrics by individual run"
            value={runId}
            onChange={(e) => setRunId(e.target.value)}
          >
            <option value="">All runs</option>
            {runOptions.map((r) => (
              <option key={r.id} value={r.id}>
                {r.title || r.slug || r.id} · {r.kind} · {fmtClock(r.startedAt)}
                {r.costUsd != null ? ` · ${fmtUsd(r.costUsd)}` : ""}
              </option>
            ))}
          </select>
        </label>
        {runId && (
          <button
            type="button"
            onClick={() => setRunId("")}
            className="btn-ghost !px-2 !py-1 text-[11.5px] text-slate-400 hover:text-slate-200"
            title="Clear individual run filter"
          >
            <IconX size={12} /> Clear run
          </button>
        )}
        <span className="relative ml-auto flex items-center">
          <span className="pointer-events-none absolute left-2.5 text-slate-500" aria-hidden>
            <IconSearch size={13} />
          </span>
          <input
            className="field w-48 py-1.5 pl-8 pr-7 text-[12.5px]"
            placeholder="Filter runs…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setQuery("")}
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="absolute right-2 text-slate-500 hover:text-slate-300"
              title="Clear"
            >
              <IconX size={12} />
            </button>
          )}
        </span>
      </div>

      {/* KPI row — values come from the filtered selection. */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <StatTile
          label="Runs"
          value={String(m?.totalRuns ?? "–")}
          sub={m?.running ? `${m.running} running now` : `${m?.succeeded ?? 0} ok · ${m?.failed ?? 0} failed`}
        />
        <StatTile
          label="Success rate"
          value={m?.successRate == null ? "–" : `${Math.round(m.successRate * 100)}%`}
          sub="finished runs"
        />
        <StatTile
          label="Total cost"
          value={fmtUsd(m?.totalCostUsd ?? null)}
          sub={costSub}
        />
        <StatTile
          label="Tokens"
          value={fmtCompact(m?.totalTokens ?? 0)}
          sub={`${fmtCompact(m?.totalTokensIn ?? 0)} in · ${fmtCompact(m?.totalTokensOut ?? 0)} out`}
        />
        <StatTile
          label="Avg duration"
          value={fmtDur(m?.avgDurationSeconds)}
          sub={`${m?.totalToolCalls ?? 0} tool calls total`}
        />
        <StatTile
          label="Retries"
          value={String(m?.totalRetries ?? 0)}
          sub="session resume fallbacks"
        />
      </div>

      {/* Charts */}
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-xl border border-white/[0.08] bg-panel p-4 shadow-card">
          <h3 className="mb-2 text-[12px] font-semibold text-slate-300">
            Cost per run
          </h3>
          <Bars points={costPoints} yFmt={(v) => fmtUsd(v)} />
        </div>
        <div className="rounded-xl border border-white/[0.08] bg-panel p-4 shadow-card">
          <h3 className="mb-2 text-[12px] font-semibold text-slate-300">
            Duration per run
          </h3>
          <Bars points={durPoints} yFmt={(v) => fmtDur(v)} />
        </div>
        <div className="rounded-xl border border-white/[0.08] bg-panel p-4 shadow-card">
          <h3 className="mb-2 text-[12px] font-semibold text-slate-300">
            Tokens per run
          </h3>
          <Bars
            points={tokenPoints}
            yFmt={(v) => fmtCompact(v)}
            stackedLabels={["Input", "Output"]}
          />
        </div>
        <div className="grid gap-3">
          <div className="rounded-xl border border-white/[0.08] bg-panel p-4 shadow-card">
            <h3 className="mb-3 text-[12px] font-semibold text-slate-300">
              Verification gates
            </h3>
            {m ? (
              <GateOutcomes metrics={m} />
            ) : (
              <div className="text-[12px] text-slate-600">no data yet</div>
            )}
          </div>
          <div className="rounded-xl border border-white/[0.08] bg-panel p-4 shadow-card">
            <h3 className="mb-2 flex items-baseline justify-between text-[12px] font-semibold text-slate-300">
              Level pass rate per run
              {m?.avgValidatorPassRate != null && (
                <span className="font-normal text-slate-500">
                  avg {Math.round(m.avgValidatorPassRate * 100)}%
                </span>
              )}
            </h3>
            <Bars points={passPoints} yFmt={(v) => `${Math.round(v)}%`} height={110} />
          </div>
        </div>
      </div>

      {/* Runs table — the accessible twin of every chart above. */}
      <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-panel shadow-card">
        <table className="w-full text-left text-[12px]">
          <thead>
            <tr className="border-b border-white/[0.06] text-[10.5px] uppercase tracking-wide text-slate-500">
              <th className="px-4 py-2.5 font-medium">Run</th>
              <th className="px-2 py-2.5 font-medium">Kind</th>
              <th className="px-2 py-2.5 font-medium">Model</th>
              <th className="px-2 py-2.5 font-medium">Status</th>
              <th className="px-2 py-2.5 text-right font-medium">Duration</th>
              <th className="px-2 py-2.5 text-right font-medium">Tokens</th>
              <th className="px-2 py-2.5 text-right font-medium">Cost</th>
              <th className="px-2 py-2.5 text-right font-medium">Turns·Tools</th>
              <th className="px-2 py-2.5 text-right font-medium">Retries</th>
              <th className="px-4 py-2.5 font-medium">Gates</th>
            </tr>
          </thead>
          <tbody>
            {runs === null ? (
              <tr>
                <td colSpan={10} className="px-4 py-8 text-center text-slate-600">
                  loading…
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={10} className="px-4 py-10 text-center text-slate-500">
                  No runs recorded yet — metrics appear here the next time the
                  agent plans or builds a concept.
                </td>
              </tr>
            ) : (
              filtered.map((r) => (
                <Fragment key={r.id}>
                  <tr
                    onClick={() => setOpenId(openId === r.id ? null : r.id)}
                    className="cursor-pointer border-b border-white/[0.04] transition-colors last:border-0 hover:bg-white/[0.03]"
                  >
                    <td className="max-w-[220px] px-4 py-2">
                      <div className="truncate font-medium text-slate-200">
                        {r.title || r.slug || r.id}
                      </div>
                      <div className="text-[10.5px] text-slate-600">
                        {fmtClock(r.startedAt)}
                      </div>
                    </td>
                    <td className="px-2 py-2 capitalize text-slate-400">{r.kind}</td>
                    <td className="max-w-[130px] truncate px-2 py-2 text-slate-400">
                      {r.model || r.driver || "–"}
                    </td>
                    <td className="px-2 py-2">
                      <span
                        className={
                          r.status === "success"
                            ? "text-emerald-300"
                            : r.status === "error"
                              ? "text-rose-300"
                              : "text-amber-300"
                        }
                      >
                        {r.status === "success"
                          ? "✓ ok"
                          : r.status === "error"
                            ? "✗ error"
                            : "● running"}
                      </span>
                    </td>
                    <td className="px-2 py-2 text-right text-slate-300" style={{ fontVariantNumeric: "tabular-nums" }}>
                      {fmtDur(r.durationSeconds)}
                    </td>
                    <td className="px-2 py-2 text-right text-slate-300" style={{ fontVariantNumeric: "tabular-nums" }}>
                      {fmtCompact(r.totalTokens)}
                    </td>
                    <td className="px-2 py-2 text-right text-slate-300" style={{ fontVariantNumeric: "tabular-nums" }}>
                      {fmtUsd(r.costUsd)}
                    </td>
                    <td className="px-2 py-2 text-right text-slate-400" style={{ fontVariantNumeric: "tabular-nums" }}>
                      {r.turns}·{r.toolCalls}
                    </td>
                    <td className="px-2 py-2 text-right text-slate-400" style={{ fontVariantNumeric: "tabular-nums" }}>
                      {r.retries}
                    </td>
                    <td className="px-4 py-2">
                      <span className="flex flex-wrap gap-1">
                        <GateChip name="lint" gate={r.gates?.lint} />
                        <GateChip name="build" gate={r.gates?.build} />
                        <GateChip name="validator" gate={r.gates?.validator} />
                      </span>
                    </td>
                  </tr>
                  {openId === r.id && (
                    <tr>
                      <td colSpan={10} className="p-0">
                        <RunDetail run={r} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
