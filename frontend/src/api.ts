export type PlanStatus =
  | "none"
  | "queued"
  | "planning"
  | "ready"
  | "building"
  | "built"
  | "error";

export interface Topic {
  id: string;
  title: string;
  blurb: string;
  notes: string;
  slug: string;
  planStatus: PlanStatus;
  plan: string;
  sessionId: string;
  planError: string;
  fullstack: boolean;
  /** Human has reviewed the built concept. Only meaningful once built. */
  reviewed: boolean;
  /** Hierarchy as a materialized path, e.g. ["Linux", "Shell"]. */
  path: string[];
}

export type AppStatus = "stopped" | "starting" | "running" | "error";
export interface AppState {
  status: AppStatus;
  url: string;
  error: string;
}

export interface Commit {
  hash: string;
  message: string;
  date: string;
}

export interface State {
  metaPrompt: string;
  topics: Topic[];
}

/** Agent driver: headless Grok Build or Claude Code CLI. */
export type AgentDriver = "grok" | "claude";

export interface GrokDriverSettings {
  model: string;
  permissionMode: string;
  reasoningEffort: string;
}

export interface ClaudeDriverSettings {
  model: string;
  permissionMode: string;
  effort: string;
  dangerouslySkipPermissions: boolean;
}

export interface FactorySettings {
  driver: AgentDriver;
  grok: GrokDriverSettings;
  claude: ClaudeDriverSettings;
}

/** One dropdown option from live CLI discovery. */
export interface CatalogOption {
  value: string;
  label: string;
  default?: boolean;
}

export interface DriverCatalog {
  driver?: string;
  models: CatalogOption[];
  defaultModel?: string;
  /** Live CLI current/default model id (e.g. fable, grok-4.5). */
  currentModel?: string;
  currentLabel?: string;
  permissionModes: CatalogOption[];
  reasoningEfforts?: CatalogOption[];
  efforts?: CatalogOption[];
  error?: string | null;
  probes?: Record<string, unknown>;
}

/** Live-discovered option catalogs (TTL-cached on the server). */
export interface SettingsCatalog {
  fetchedAt: number;
  fetchedAtIso: string;
  elapsedMs?: number;
  ttlSeconds?: number;
  source: string;
  cache?: string;
  ageSeconds?: number;
  stale?: boolean;
  error?: string | null;
  grok: DriverCatalog;
  claude: DriverCatalog;
}

/** Prepaid $ remaining from console.x.ai (Management API). */
export interface Credits {
  ok: boolean;
  currency: string;
  label: string;
  detail: string;
  source?: string;
  spentUsd: number;
  sessionSpendUsd: number;
  /** Prepaid issued total (compat field name). */
  budgetUsd: number | null;
  remainingUsd: number | null;
  prepaidIssuedUsd?: number | null;
  prepaidUsedUsd?: number | null;
  /** % of prepaid pack remaining (for the bar). */
  pct: number | null;
  error?: string | null;
  remainingTokens?: number | null;
  limitTokens?: number | null;
}

// --- Run instrumentation (persisted per-run logs + metrics) -----------------
export type RunKind = "plan" | "refine" | "consolidate" | "build" | "improve";
export type RunStatus = "running" | "success" | "error";
export type GateStatus = "pass" | "fail" | "skipped" | "error";

export interface LevelResult {
  id: number;
  topic: string;
  ok: boolean;
  reason: string;
}

export interface GateResult {
  status: GateStatus;
  detail?: string;
  /** Validator gate only: auto-played level results. */
  passed?: number;
  total?: number;
  passRate?: number;
  levels?: LevelResult[];
}

export interface RunRecord {
  id: string;
  kind: RunKind | string;
  topicId: string;
  slug: string;
  title: string;
  driver: string;
  driverLabel: string;
  model: string;
  effort: string;
  permissionMode: string;
  status: RunStatus;
  error: string;
  sessionId: string;
  startedAt: number;
  startedAtIso: string;
  endedAt: number | null;
  endedAtIso: string | null;
  durationSeconds: number | null;
  tokensIn: number;
  tokensOut: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
  totalTokens: number;
  costUsd: number | null;
  turns: number;
  toolCalls: number;
  retries: number;
  attempts: number;
  exitCode: number | null;
  eventCount: number;
  logLines: number;
  gates: { lint: GateResult; build: GateResult; validator: GateResult };
}

export interface RunMetrics {
  totalRuns: number;
  running: number;
  succeeded: number;
  failed: number;
  successRate: number | null;
  totalCostUsd: number;
  totalTokensIn: number;
  totalTokensOut: number;
  totalTokens: number;
  totalToolCalls: number;
  totalRetries: number;
  avgDurationSeconds: number | null;
  gates: Record<
    "lint" | "build" | "validator",
    { pass: number; fail: number; skipped: number }
  >;
  avgValidatorPassRate: number | null;
  byModel: Record<
    string,
    { runs: number; costUsd: number; tokens: number; success: number; finished: number }
  >;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  getState: () => fetch("/api/state").then(json<State>),

  setMetaPrompt: (metaPrompt: string) =>
    fetch("/api/meta-prompt", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ metaPrompt }),
    }).then(json<State>),

  createTopic: (title: string) =>
    fetch("/api/topics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }).then(json<Topic>),

  createTopicsBulk: (text: string) =>
    fetch("/api/topics/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }).then(json<Topic[]>),

  updateTopic: (id: string, patch: Partial<Omit<Topic, "id">>) =>
    fetch(`/api/topics/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).then(json<Topic>),

  deleteTopic: (id: string) =>
    fetch(`/api/topics/${id}`, { method: "DELETE" }).then(json<{ ok: boolean }>),

  deleteAllTopics: () =>
    fetch("/api/topics", { method: "DELETE" }).then(
      json<{ ok: boolean; deleted: number }>
    ),

  generatePlans: () =>
    fetch("/api/plans/generate", { method: "POST" }).then(
      json<{ queued: number; concurrency: number }>
    ),

  generateOnePlan: (id: string) =>
    fetch(`/api/topics/${id}/plan`, { method: "POST" }).then(json<Topic>),

  consolidateTopics: (ids: string[]) =>
    fetch("/api/topics/consolidate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    }).then(json<Topic>),

  refinePlan: (id: string, prompt: string) =>
    fetch(`/api/topics/${id}/plan/refine`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    }).then(json<Topic>),

  savePlan: (id: string, plan: string) =>
    fetch(`/api/topics/${id}/plan`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan }),
    }).then(json<Topic>),

  buildTopic: (id: string) =>
    fetch(`/api/topics/${id}/build`, { method: "POST" }).then(json<Topic>),

  getLog: (id: string) =>
    fetch(`/api/topics/${id}/log`).then(
      json<{ status: PlanStatus; lines: string[] }>
    ),

  launchApp: (slug: string) =>
    fetch(`/api/concepts/${slug}/launch`, { method: "POST" }).then(json<AppState>),

  stopApp: (slug: string) =>
    fetch(`/api/concepts/${slug}/stop`, { method: "POST" }).then(json<AppState>),

  appStatus: (slug: string) =>
    fetch(`/api/concepts/${slug}/app`).then(json<AppState>),

  improveApp: (id: string, prompt: string) =>
    fetch(`/api/topics/${id}/improve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    }).then(json<Topic>),

  getHistory: (id: string) =>
    fetch(`/api/topics/${id}/history`).then(json<{ commits: Commit[] }>),

  revertTo: (id: string, hash: string) =>
    fetch(`/api/topics/${id}/revert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hash }),
    }).then(json<Topic>),

  getCredits: (force = false) =>
    fetch(`/api/credits${force ? "?force=1" : ""}`).then(json<Credits>),

  getSettings: () => fetch("/api/settings").then(json<FactorySettings>),

  setSettings: (settings: Partial<FactorySettings>) =>
    fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }).then(json<FactorySettings>),

  /** Live CLI-discovered models/enums (TTL-cached; force re-polls). */
  getSettingsCatalog: (force = false) =>
    fetch(`/api/settings/catalog${force ? "?force=1" : ""}`).then(
      json<SettingsCatalog>
    ),

  /**
   * Optional combined poll (catalog + settings). Not required for open —
   * the modal uses getSettings + getSettingsCatalog so older servers work.
   */
  bootstrapSettings: () =>
    fetch("/api/settings/bootstrap").then(
      json<{ catalog: SettingsCatalog; settings: FactorySettings }>
    ),

  /**
   * Bust TTL and re-poll CLIs. Returns catalog + settings with models synced
   * to the live CLI current selection.
   */
  refreshSettingsCatalog: () =>
    fetch("/api/settings/catalog/refresh", { method: "POST" }).then(
      json<{ catalog: SettingsCatalog; settings: FactorySettings }>
    ),

  /** Structured per-run records, newest first. */
  listRuns: (opts: { topicId?: string; kind?: string; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.topicId) params.set("topicId", opts.topicId);
    if (opts.kind) params.set("kind", opts.kind);
    if (opts.limit) params.set("limit", String(opts.limit));
    const qs = params.toString();
    return fetch(`/api/runs${qs ? `?${qs}` : ""}`).then(
      json<{ runs: RunRecord[] }>
    );
  },

  getRun: (id: string) => fetch(`/api/runs/${id}`).then(json<RunRecord>),

  getRunEvents: (id: string, offset = 0, limit = 500) =>
    fetch(`/api/runs/${id}/events?offset=${offset}&limit=${limit}`).then(
      json<{ events: Record<string, unknown>[]; offset: number; total: number }>
    ),

  getRunLog: (id: string) =>
    fetch(`/api/runs/${id}/log`).then(json<{ lines: string[] }>),

  getRunMetrics: () => fetch("/api/runs/metrics").then(json<RunMetrics>),
};

/** Download URL for a run export (json bundle | raw ndjson events | txt log). */
export const runExportUrl = (id: string, format: "json" | "ndjson" | "txt") =>
  `/api/runs/${id}/export?format=${format}`;

/** URL where a built concept is served (via the backend / dev proxy). */
export const conceptUrl = (slug: string) => `/concepts/${slug}/`;
