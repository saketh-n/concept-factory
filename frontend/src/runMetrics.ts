/**
 * Pure helpers for the Runs metrics dashboard: filter a run list and compute
 * KPI aggregates client-side so kind / search / individual-run selection all
 * scope the same numbers (tiles, charts, table).
 */
import type { RunMetrics, RunRecord } from "./api";

export interface RunFilter {
  kind?: string;
  query?: string;
  /** When set, only this run id is kept (after kind/query). */
  runId?: string;
}

/** Filter runs by kind, free-text query, and optional individual run id. */
export function filterRuns(
  runs: RunRecord[],
  { kind = "", query = "", runId = "" }: RunFilter = {}
): RunRecord[] {
  let list = runs;
  if (kind) list = list.filter((r) => r.kind === kind);
  const q = query.trim().toLowerCase();
  if (q) {
    list = list.filter((r) =>
      [r.title, r.slug, r.model, r.driver, r.id].join(" ").toLowerCase().includes(q)
    );
  }
  if (runId) list = list.filter((r) => r.id === runId);
  return list;
}

/** Aggregate KPI metrics from an arbitrary run list (filtered selection). */
export function metricsFromRuns(runs: RunRecord[]): RunMetrics {
  const finished = runs.filter((r) => r.status === "success" || r.status === "error");
  const succeeded = finished.filter((r) => r.status === "success");

  const gateCounts = (name: "lint" | "build" | "validator") => {
    const counts = { pass: 0, fail: 0, skipped: 0 };
    for (const r of runs) {
      const status = r.gates?.[name]?.status;
      if (status === "pass" || status === "fail" || status === "skipped") {
        counts[status] += 1;
      } else if (status) {
        counts.fail += 1;
      }
    }
    return counts;
  };

  const validatorRates = runs
    .map((r) => r.gates?.validator?.passRate)
    .filter((v): v is number => typeof v === "number");

  const durations = finished
    .map((r) => r.durationSeconds)
    .filter((v): v is number => v != null);

  const byModel: RunMetrics["byModel"] = {};
  for (const r of runs) {
    const key = `${r.driver || "?"}/${r.model || "default"}`;
    const b = byModel[key] ?? {
      runs: 0,
      costUsd: 0,
      tokens: 0,
      success: 0,
      finished: 0,
    };
    b.runs += 1;
    b.costUsd = Math.round((b.costUsd + (r.costUsd ?? 0)) * 1e6) / 1e6;
    b.tokens += r.totalTokens || 0;
    if (r.status === "success" || r.status === "error") {
      b.finished += 1;
      if (r.status === "success") b.success += 1;
    }
    byModel[key] = b;
  }

  return {
    totalRuns: runs.length,
    running: runs.filter((r) => r.status === "running").length,
    succeeded: succeeded.length,
    failed: finished.length - succeeded.length,
    successRate: finished.length
      ? Math.round((succeeded.length / finished.length) * 1e4) / 1e4
      : null,
    totalCostUsd:
      Math.round(runs.reduce((s, r) => s + (r.costUsd ?? 0), 0) * 1e6) / 1e6,
    totalTokensIn: runs.reduce((s, r) => s + (r.tokensIn || 0), 0),
    totalTokensOut: runs.reduce((s, r) => s + (r.tokensOut || 0), 0),
    totalTokens: runs.reduce((s, r) => s + (r.totalTokens || 0), 0),
    totalToolCalls: runs.reduce((s, r) => s + (r.toolCalls || 0), 0),
    totalRetries: runs.reduce((s, r) => s + (r.retries || 0), 0),
    avgDurationSeconds: durations.length
      ? Math.round((durations.reduce((a, b) => a + b, 0) / durations.length) * 1e3) /
        1e3
      : null,
    gates: {
      lint: gateCounts("lint"),
      build: gateCounts("build"),
      validator: gateCounts("validator"),
    },
    avgValidatorPassRate: validatorRates.length
      ? Math.round(
          (validatorRates.reduce((a, b) => a + b, 0) / validatorRates.length) * 1e4
        ) / 1e4
      : null,
    byModel,
  };
}
