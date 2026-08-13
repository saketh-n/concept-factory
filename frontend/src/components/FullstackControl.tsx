import { useEffect, useState } from "react";
import { api, type AppState } from "../api";
import { usePolling } from "../hooks/usePolling";

/** Launch / open / stop controls for a full-stack concept that runs its own
 *  backend (served on a remapped port, not statically). */
export default function FullstackControl({ slug }: { slug: string }) {
  const [app, setApp] = useState<AppState>({ status: "stopped", url: "", error: "" });
  const [busy, setBusy] = useState(false);

  const starting = app.status === "starting";

  // Poll while starting so the UI flips to "Open" once the app is reachable.
  usePolling(
    async () => {
      try {
        setApp(await api.appStatus(slug));
      } catch {
        /* ignore */
      }
    },
    starting ? 1500 : null,
    { restartKey: slug }
  );

  // Pick up an already-running app on mount (e.g. after a page reload).
  useEffect(() => {
    api.appStatus(slug).then(setApp).catch(() => {});
  }, [slug]);

  const launch = async () => {
    setBusy(true);
    try {
      setApp(await api.launchApp(slug));
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    try {
      setApp(await api.stopApp(slug));
    } finally {
      setBusy(false);
    }
  };

  if (app.status === "running") {
    return (
      <div className="flex items-center justify-between rounded-lg bg-emerald-400/15 px-3 py-2 font-mono text-[11.5px] font-medium text-emerald-200 ring-1 ring-inset ring-emerald-400/30">
        <span>App running</span>
        <span className="flex items-center gap-3">
          <a href={app.url} target="_blank" rel="noreferrer" className="hover:opacity-80">
            Open app →
          </a>
          <button onClick={stop} disabled={busy} className="opacity-80 hover:opacity-100">
            Stop
          </button>
        </span>
      </div>
    );
  }

  if (starting) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-violet-400/10 px-3 py-2 font-mono text-[11.5px] font-medium text-violet-300 ring-1 ring-inset ring-violet-400/25">
        <span className="h-2 w-2 animate-pulse rounded-full bg-current" />
        Starting app… (first launch installs deps)
      </div>
    );
  }

  if (app.status === "error") {
    return (
      <div className="flex items-center justify-between rounded-lg bg-rose-400/10 px-3 py-2 font-mono text-[11.5px] font-medium text-rose-300 ring-1 ring-inset ring-rose-400/25">
        <span className="mr-2 truncate" title={app.error}>
          {app.error || "Failed to launch"}
        </span>
        <button onClick={launch} disabled={busy} className="shrink-0 hover:opacity-80">
          Retry
        </button>
      </div>
    );
  }

  return (
    <button
      onClick={launch}
      disabled={busy}
      className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 font-mono text-[11.5px] font-medium text-slate-300 transition hover:border-violet-400/30 hover:text-violet-200 disabled:opacity-50"
    >
      <span>Full-stack concept</span>
      <span>{busy ? "Launching…" : "Launch app →"}</span>
    </button>
  );
}
