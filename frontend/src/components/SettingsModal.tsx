import { useEffect, useMemo, useState } from "react";
import {
  api,
  type AgentDriver,
  type CatalogOption,
  type FactorySettings,
  type SettingsCatalog,
} from "../api";
import { IconRefresh, IconSettings, IconX } from "./icons";

interface Props {
  onClose: () => void;
}

/** Ensure the currently saved value remains selectable even if discovery lagged. */
function withCurrent(options: CatalogOption[] | undefined, current: string): CatalogOption[] {
  const list = [...(options || [])];
  if (current && !list.some((o) => o.value === current)) {
    list.unshift({ value: current, label: `${current} (saved)` });
  }
  return list;
}

export default function SettingsModal({ onClose }: Props) {
  const [draft, setDraft] = useState<FactorySettings | null>(null);
  const [catalog, setCatalog] = useState<SettingsCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  useEffect(() => {
    let alive = true;
    // Reliable open path: stored settings (fast) + catalog (TTL-cached).
    // Do NOT depend solely on /bootstrap — older/running servers may 404 it
    // and leave the modal blank forever.
    setLoading(true);
    setCatalogLoading(true);
    setError(null);

    api
      .getSettings()
      .then((s) => {
        if (!alive) return;
        setDraft(s);
        setLoading(false);
      })
      .catch((e: Error) => {
        if (!alive) return;
        setError(e.message || "Failed to load settings");
        setLoading(false);
      });

    api
      .getSettingsCatalog()
      .then((cat) => {
        if (!alive) return;
        setCatalog(cat);
        // Prefer CLI current models when stored value is empty / bootstrap.
        setDraft((prev) => {
          if (!prev) return prev;
          const next = { ...prev, grok: { ...prev.grok }, claude: { ...prev.claude } };
          const gCur = cat.grok?.currentModel || "";
          const cCur = cat.claude?.currentModel || "";
          if (gCur && !next.grok.model) next.grok.model = gCur;
          if (
            cCur &&
            (!next.claude.model || next.claude.model === "sonnet")
          ) {
            next.claude.model = cCur;
          }
          return next;
        });
      })
      .catch((e: Error) => {
        if (!alive) return;
        setError((prev) => prev || e.message || "Failed to load model catalog");
      })
      .finally(() => {
        if (alive) setCatalogLoading(false);
      });

    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Real-time: reflect CLI-side `/model` changes without a manual re-poll.
  useEffect(() => {
    const unsubscribe = api.subscribeCurrentModels((data) => {
      setCatalog((prev) => {
        if (!prev) return prev;
        const gCur = data.grok?.currentModel ?? prev.grok?.currentModel ?? "";
        const cCur = data.claude?.currentModel ?? prev.claude?.currentModel ?? "";
        return {
          ...prev,
          grok: { ...prev.grok, currentModel: gCur },
          claude: { ...prev.claude, currentModel: cCur },
        };
      });
    });
    return unsubscribe;
  }, []);

  const setDriver = (driver: AgentDriver) => {
    setDraft((prev) => (prev ? { ...prev, driver } : prev));
  };

  const patchGrok = (patch: Partial<FactorySettings["grok"]>) => {
    setDraft((prev) =>
      prev ? { ...prev, grok: { ...prev.grok, ...patch } } : prev
    );
  };

  const patchClaude = (patch: Partial<FactorySettings["claude"]>) => {
    setDraft((prev) =>
      prev ? { ...prev, claude: { ...prev.claude, ...patch } } : prev
    );
  };

  const refreshCatalog = async () => {
    setRefreshing(true);
    setError(null);
    try {
      // Prefer refresh endpoint (busts TTL + returns synced settings). Fall
      // back to force catalog + settings if refresh shape/route differs.
      try {
        const { catalog: cat, settings } = await api.refreshSettingsCatalog();
        setCatalog(cat);
        setDraft(settings);
      } catch {
        const cat = await api.getSettingsCatalog(true);
        setCatalog(cat);
        const s = await api.getSettings();
        setDraft(s);
      }
    } catch (e) {
      setError((e as Error).message || "Catalog refresh failed");
    } finally {
      setRefreshing(false);
    }
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.setSettings(draft);
      setDraft(saved);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 1600);
    } catch (e) {
      setError((e as Error).message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const driver = draft?.driver ?? "grok";

  const grokModels = useMemo(
    () => withCurrent(catalog?.grok?.models, draft?.grok.model ?? ""),
    [catalog, draft?.grok.model]
  );
  const grokPerms = useMemo(
    () => withCurrent(catalog?.grok?.permissionModes, draft?.grok.permissionMode ?? ""),
    [catalog, draft?.grok.permissionMode]
  );
  const grokReasoning = useMemo(
    () => withCurrent(catalog?.grok?.reasoningEfforts, draft?.grok.reasoningEffort ?? ""),
    [catalog, draft?.grok.reasoningEffort]
  );
  const claudeModels = useMemo(
    () => withCurrent(catalog?.claude?.models, draft?.claude.model ?? ""),
    [catalog, draft?.claude.model]
  );
  const claudePerms = useMemo(
    () => withCurrent(catalog?.claude?.permissionModes, draft?.claude.permissionMode ?? ""),
    [catalog, draft?.claude.permissionMode]
  );
  const claudeEfforts = useMemo(
    () => withCurrent(catalog?.claude?.efforts, draft?.claude.effort ?? ""),
    [catalog, draft?.claude.effort]
  );

  const cliCurrentNote =
    driver === "grok"
      ? catalog?.grok?.currentModel
        ? `CLI current: ${catalog.grok.currentModel}`
        : ""
      : catalog?.claude?.currentModel
        ? `CLI current: ${catalog.claude.currentModel}${
            catalog.claude.currentLabel
              ? ` (${catalog.claude.currentLabel})`
              : ""
          }`
        : "";

  const catalogNote = catalog
    ? `${
        catalog.cache === "memory" || catalog.cache === "memory-stale"
          ? `Cached${
              typeof catalog.ageSeconds === "number"
                ? ` (${Math.round(catalog.ageSeconds)}s old)`
                : ""
            }`
          : `Polled live${
              typeof catalog.elapsedMs === "number"
                ? ` in ${catalog.elapsedMs}ms`
                : ""
            }`
      }${catalog.fetchedAtIso ? ` · ${catalog.fetchedAtIso}` : ""}${
        cliCurrentNote ? ` · ${cliCurrentNote}` : ""
      }`
    : "Polling CLIs for models…";

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 px-4 py-10 backdrop-blur-sm sm:py-16"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-lg overflow-hidden rounded-2xl border border-white/10 bg-[#0f1524] shadow-2xl shadow-black/50">
        <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-emerald-400/15 text-emerald-300">
              <IconSettings size={14} />
            </span>
            <div>
              <h2
                id="settings-title"
                className="font-display text-[15px] font-semibold text-slate-50"
              >
                Agent settings
              </h2>
              <p className="text-[11.5px] text-slate-500">
                Choose the headless driver for plan, build, refine, and improve
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={refreshCatalog}
              disabled={refreshing || catalogLoading}
              className="btn-ghost !px-2 text-slate-500"
              title="Re-poll Grok/Claude for models and options"
              aria-label="Refresh model catalog from CLIs"
            >
              <IconRefresh size={14} />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="btn-ghost !px-2 text-slate-500"
              title="Close"
              aria-label="Close settings"
            >
              <IconX size={16} />
            </button>
          </div>
        </div>

        <div className="space-y-5 px-5 py-5">
          {loading || !draft ? (
            <div className="space-y-3" aria-label="Loading settings">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-12 animate-pulse rounded-lg bg-white/[0.04]"
                />
              ))}
            </div>
          ) : (
            <>
              <fieldset>
                <legend className="mb-2 font-mono text-[11px] uppercase tracking-[0.14em] text-slate-500">
                  Driver
                </legend>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setDriver("grok")}
                    aria-pressed={driver === "grok"}
                    className={`rounded-xl border px-3 py-3 text-left transition ${
                      driver === "grok"
                        ? "border-emerald-400/45 bg-emerald-400/10 ring-1 ring-emerald-400/25"
                        : "border-white/10 bg-white/[0.03] hover:border-white/20"
                    }`}
                  >
                    <div className="text-[13px] font-semibold text-slate-100">
                      Grok Build
                    </div>
                    <div className="mt-0.5 text-[11.5px] leading-snug text-slate-500">
                      Headless <code className="text-slate-400">grok</code> CLI
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setDriver("claude")}
                    aria-pressed={driver === "claude"}
                    className={`rounded-xl border px-3 py-3 text-left transition ${
                      driver === "claude"
                        ? "border-violet-400/45 bg-violet-400/10 ring-1 ring-violet-400/25"
                        : "border-white/10 bg-white/[0.03] hover:border-white/20"
                    }`}
                  >
                    <div className="text-[13px] font-semibold text-slate-100">
                      Claude Code
                    </div>
                    <div className="mt-0.5 text-[11.5px] leading-snug text-slate-500">
                      Headless <code className="text-slate-400">claude</code>{" "}
                      CLI
                    </div>
                  </button>
                </div>
              </fieldset>

              <p className="text-[11px] leading-relaxed text-slate-600">
                {refreshing ? "Re-polling installed CLIs…" : catalogNote}
                {catalog?.grok?.error || catalog?.claude?.error ? (
                  <span className="mt-1 block text-amber-400/90">
                    {[catalog?.grok?.error, catalog?.claude?.error]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                ) : null}
              </p>

              {driver === "grok" ? (
                <div className="space-y-3.5 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
                  <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-emerald-400/80">
                    Grok Build options
                  </div>
                  <label className="block">
                    <span className="mb-1 block text-[12px] font-medium text-slate-400">
                      Model
                    </span>
                    <select
                      className="field w-full"
                      value={draft.grok.model}
                      onChange={(e) => patchGrok({ model: e.target.value })}
                      disabled={catalogLoading && grokModels.length === 0}
                    >
                      {grokModels.length === 0 ? (
                        <option value={draft.grok.model || ""}>
                          {catalogLoading ? "Loading models…" : "No models discovered"}
                        </option>
                      ) : (
                        grokModels.map((m) => (
                          <option key={m.value || "default"} value={m.value}>
                            {m.label}
                          </option>
                        ))
                      )}
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-[12px] font-medium text-slate-400">
                      Permission mode
                    </span>
                    <select
                      className="field w-full"
                      value={draft.grok.permissionMode}
                      onChange={(e) =>
                        patchGrok({ permissionMode: e.target.value })
                      }
                    >
                      {grokPerms.map((m) => (
                        <option key={m.value || "empty"} value={m.value}>
                          {m.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-[12px] font-medium text-slate-400">
                      Reasoning effort
                    </span>
                    <select
                      className="field w-full"
                      value={draft.grok.reasoningEffort}
                      onChange={(e) =>
                        patchGrok({ reasoningEffort: e.target.value })
                      }
                    >
                      {(grokReasoning.length
                        ? grokReasoning
                        : [{ value: "", label: "Default" }]
                      ).map((m) => (
                        <option key={m.value || "default"} value={m.value}>
                          {m.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1 flex items-center justify-between gap-2 text-[12px] font-medium text-slate-400">
                      <span>Max build budget</span>
                      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-600">
                        USD · empty = unlimited
                      </span>
                    </span>
                    <div className="relative">
                      <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm text-slate-500">
                        $
                      </span>
                      <input
                        type="number"
                        min={0}
                        step="0.5"
                        inputMode="decimal"
                        placeholder="Unlimited"
                        className="field w-full pl-7"
                        value={draft.grok.maxBuildBudgetUsd ?? ""}
                        onChange={(e) =>
                          patchGrok({ maxBuildBudgetUsd: e.target.value })
                        }
                      />
                    </div>
                    <span className="mt-1 block text-[11px] leading-relaxed text-slate-600">
                      Caps each Approve &amp; build via Grok&apos;s goal token
                      budget. Leave empty for no cap. Pre-fills the build
                      dialog; you can still override per build.
                    </span>
                  </label>
                  <p className="text-[11.5px] leading-relaxed text-slate-600">
                    Unattended runs always pass{" "}
                    <code className="text-slate-500">--always-approve</code>.
                    Builds request{" "}
                    <code className="text-slate-500">bypassPermissions</code>.
                  </p>
                </div>
              ) : (
                <div className="space-y-3.5 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
                  <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-violet-400/80">
                    Claude Code options
                  </div>
                  <label className="block">
                    <span className="mb-1 block text-[12px] font-medium text-slate-400">
                      Model
                    </span>
                    <select
                      className="field w-full"
                      value={draft.claude.model}
                      onChange={(e) => patchClaude({ model: e.target.value })}
                      disabled={catalogLoading && claudeModels.length === 0}
                    >
                      {claudeModels.length === 0 ? (
                        <option value={draft.claude.model || ""}>
                          {catalogLoading ? "Loading models…" : "No models discovered"}
                        </option>
                      ) : (
                        claudeModels.map((m) => (
                          <option key={m.value} value={m.value}>
                            {m.label}
                          </option>
                        ))
                      )}
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-[12px] font-medium text-slate-400">
                      Permission mode
                    </span>
                    <select
                      className="field w-full"
                      value={draft.claude.permissionMode}
                      onChange={(e) =>
                        patchClaude({ permissionMode: e.target.value })
                      }
                      disabled={draft.claude.dangerouslySkipPermissions}
                    >
                      {claudePerms.map((m) => (
                        <option key={m.value || "empty"} value={m.value}>
                          {m.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-[12px] font-medium text-slate-400">
                      Effort
                    </span>
                    <select
                      className="field w-full"
                      value={draft.claude.effort}
                      onChange={(e) => patchClaude({ effort: e.target.value })}
                    >
                      {(claudeEfforts.length
                        ? claudeEfforts
                        : [{ value: "", label: "Default" }]
                      ).map((m) => (
                        <option key={m.value || "default"} value={m.value}>
                          {m.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2.5">
                    <input
                      type="checkbox"
                      className="mt-0.5 accent-violet-400"
                      checked={draft.claude.dangerouslySkipPermissions}
                      onChange={(e) =>
                        patchClaude({
                          dangerouslySkipPermissions: e.target.checked,
                        })
                      }
                    />
                    <span>
                      <span className="block text-[12.5px] font-medium text-slate-200">
                        Skip all permissions
                      </span>
                      <span className="block text-[11px] leading-snug text-slate-500">
                        Passes{" "}
                        <code className="text-slate-400">
                          --dangerously-skip-permissions
                        </code>{" "}
                        so factory jobs never hang on TTY prompts.
                      </span>
                    </span>
                  </label>
                </div>
              )}

              {error && (
                <p className="rounded-lg border border-rose-400/25 bg-rose-400/10 px-3 py-2 text-[12.5px] text-rose-200">
                  {error}
                </p>
              )}
            </>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-white/[0.07] bg-white/[0.015] px-5 py-3">
          <span className="text-[11.5px] text-slate-600">
            {savedFlash
              ? "Saved — next agent jobs use these settings."
              : "Applies to plan, build, refine, improve, consolidate."}
          </span>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} className="btn-secondary">
              Close
            </button>
            <button
              type="button"
              onClick={save}
              disabled={!draft || saving}
              className="btn-primary"
            >
              {saving ? "Saving…" : savedFlash ? "Saved" : "Save settings"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
