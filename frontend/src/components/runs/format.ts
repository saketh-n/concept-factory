// Shared number/time formatting for the runs dashboard.

export const fmtCompact = (n: number): string => {
  if (!isFinite(n)) return "–";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
  return `${Math.round(n)}`;
};

export const fmtUsd = (n: number | null | undefined): string => {
  if (n == null) return "–";
  if (n !== 0 && Math.abs(n) < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
};

export const fmtDur = (s: number | null | undefined): string => {
  if (s == null) return "–";
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${Math.round(s % 60)}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
};

export const fmtClock = (ts: number): string =>
  new Date(ts * 1000).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
