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
}

export interface State {
  metaPrompt: string;
  topics: Topic[];
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
};

/** URL where a built concept is served (via the backend / dev proxy). */
export const conceptUrl = (slug: string) => `/concepts/${slug}/`;
