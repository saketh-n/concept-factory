import { useEffect, useMemo, useState } from "react";
import {
  api,
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
        // Prefer CLI current model when stored value is empty.
        setDraft((prev) => {
          if (!prev) return prev;
          const next = { ...prev, driver: "grok" as const, grok: { ...prev.grok } };
          const gCur = cat.grok?.currentModel || "";
          if (gCur && !next.grok.model) next.grok.model = gCur;
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
        return {
          ...prev,
          grok: { ...prev.grok, currentModel: gCur },
        };
      });
    });
    return unsubscribe;
  }, []);

  const patchGrok = (patch: Partial<FactorySettings["grok"]>) => {
    setDraft((prev) =>
      prev ? { ...prev, driver: "grok", grok: { ...prev.grok, ...patch } } : prev
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
      const saved = await api.setSettings({ ...draft, driver: "grok" });
      setDraft(saved);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 1600);
    } catch (e) {
      setError((e as Error).message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

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

  const cliCurrentNote = catalog?.grok?.currentModel
    ? `CLI current: ${catalog.grok.currentModel}`
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
    : "Polling Grok for models…";

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
                Grok Build options for plan, build, refine, and improve
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={refreshCatalog}
              disabled={refreshing || catalogLoading}
              className="btn-ghost !px-2 text-slate-500"
              title="Re-poll Grok for models and options"
              aria-label="Refresh model catalog from Grok CLI"
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
              <div className="flex items-center gap-3 rounded-xl border border-emerald-400/25 bg-emerald-400/[0.07] px-3.5 py-3">
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-semibold text-slate-100">
                    Grok Build
                  </div>
                  <div className="mt-0.5 text-[11.5px] leading-snug text-slate-500">
                    Sole headless driver —{" "}
                    <code className="text-slate-400">grok</code> CLI for every
                    factory job
                  </div>
                </div>
                <span className="shrink-0 rounded-full bg-emerald-400/15 px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-emerald-300 ring-1 ring-inset ring-emerald-400/30">
                  active
                </span>
              </div>

              <p className="text-[11px] leading-relaxed text-slate-600">
                {refreshing ? "Re-polling Grok CLI…" : catalogNote}
                {catalog?.grok?.error ? (
                  <span className="mt-1 block text-amber-400/90">
                    {catalog.grok.error}
                  </span>
                ) : null}
              </p>

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
