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
};

/** URL where a built concept is served (via the backend / dev proxy). */
export const conceptUrl = (slug: string) => `/concepts/${slug}/`;
