import { Fragment, useEffect, useMemo, useState } from "react";
import {
  api,
  type RunMetrics,
  type RunRecord,
} from "../../api";
import { filterRuns, metricsFromRuns } from "../../runMetrics";
import { usePolling } from "../../hooks/usePolling";
import { IconSearch, IconX } from "../icons";
import { Bars, type BarPoint } from "./charts";
import { fmtClock, fmtCompact, fmtDur, fmtUsd } from "./format";
import { GateOutcomes, StatTile } from "./StatTiles";
import { GateChip, RunDetail } from "./RunDetail";

/**
 * Runs & metrics dashboard: every agent run (plan / refine / consolidate /
 * build / improve) is persisted server-side with structured metrics — this
 * view charts them and drills into any run's full log + raw event stream.
 */
const KINDS = ["plan", "refine", "consolidate", "build", "improve"] as const;

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
