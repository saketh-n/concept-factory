/**
 * Hermetic tests for client-side run filtering + KPI aggregation.
 * Run: npx --yes tsx src/runMetrics.test.ts  (from frontend/)
 */
import { filterRuns, metricsFromRuns } from "./runMetrics";
import type { RunRecord } from "./api";

function base(partial: Partial<RunRecord> & Pick<RunRecord, "id">): RunRecord {
  return {
    kind: "build",
    topicId: "t",
    slug: "slug",
    title: "Title",
    driver: "grok",
    driverLabel: "Grok",
    model: "grok-4.5",
    effort: "",
    permissionMode: "",
    status: "success",
    error: "",
    sessionId: "",
    startedAt: 1,
    startedAtIso: "",
    endedAt: 2,
    endedAtIso: "",
    durationSeconds: 10,
    tokensIn: 100,
    tokensOut: 50,
    cacheReadTokens: 0,
    cacheCreationTokens: 0,
    totalTokens: 150,
    costUsd: 0.5,
    turns: 1,
    toolCalls: 0,
    retries: 0,
    attempts: 1,
    exitCode: 0,
    eventCount: 1,
    logLines: 1,
    gates: {
      lint: { status: "pass" },
      build: { status: "pass" },
      validator: { status: "skipped" },
    },
    ...partial,
  };
}

const a = base({
  id: "run_a",
  kind: "build",
  title: "Reinforcement Learning",
  costUsd: 0.56947,
  tokensIn: 1000,
  tokensOut: 200,
  totalTokens: 1200,
  durationSeconds: 100,
});
const b = base({
  id: "run_b",
  kind: "plan",
  title: "Regex",
  costUsd: 0.1,
  tokensIn: 50,
  tokensOut: 20,
  totalTokens: 70,
  durationSeconds: 20,
  status: "error",
});
const c = base({
  id: "run_c",
  kind: "build",
  title: "Other",
  costUsd: null,
  tokensIn: 10,
  tokensOut: 5,
  totalTokens: 15,
  durationSeconds: 5,
});

let failed = 0;
function assert(cond: unknown, msg: string) {
  if (!cond) {
    console.error("FAIL:", msg);
    failed += 1;
  } else {
    console.log("ok:", msg);
  }
}

// filter by kind
assert(filterRuns([a, b, c], { kind: "build" }).map((r) => r.id).join() === "run_a,run_c", "kind filter");

// filter by query
assert(filterRuns([a, b, c], { query: "reinforcement" }).map((r) => r.id).join() === "run_a", "query filter");

// individual run filter
const one = filterRuns([a, b, c], { runId: "run_a" });
assert(one.length === 1 && one[0].id === "run_a", "individual run filter");

// compose kind + runId
assert(
  filterRuns([a, b, c], { kind: "plan", runId: "run_a" }).length === 0,
  "runId outside kind yields empty"
);
assert(
  filterRuns([a, b, c], { kind: "build", runId: "run_a" }).map((r) => r.id).join() === "run_a",
  "runId + kind compose"
);

// metrics for all runs
const all = metricsFromRuns([a, b, c]);
assert(all.totalRuns === 3, "totalRuns");
assert(Math.abs(all.totalCostUsd - 0.66947) < 1e-6, `totalCostUsd=${all.totalCostUsd}`);
assert(all.succeeded === 2 && all.failed === 1, "success/fail counts");
assert(all.totalTokens === 1200 + 70 + 15, "totalTokens");

// metrics scoped to one run — KPI tiles must equal that run
const scoped = metricsFromRuns(filterRuns([a, b, c], { runId: "run_a" }));
assert(scoped.totalRuns === 1, "scoped totalRuns");
assert(Math.abs(scoped.totalCostUsd - 0.56947) < 1e-6, `scoped cost=${scoped.totalCostUsd}`);
assert(scoped.totalTokensIn === 1000, "scoped tokensIn");
assert(scoped.avgDurationSeconds === 100, "scoped avg duration");
assert(scoped.succeeded === 1 && scoped.failed === 0, "scoped status");

// clearing runId restores multi-run (simulate)
const restored = metricsFromRuns(filterRuns([a, b, c], { runId: "" }));
assert(restored.totalRuns === 3, "clear run restores multi-run");

if (failed) {
  console.error(`\n${failed} assertion(s) failed`);
  throw new Error(`${failed} assertion(s) failed`);
}
console.log("\nall runMetrics tests passed");
