import { type RunMetrics } from "../../api";
import { STATUS_BAD, STATUS_GOOD, STATUS_SKIP } from "./charts";

/** One horizontal pass/fail/skipped band per gate — counts always labeled. */
export function GateOutcomes({ metrics }: { metrics: RunMetrics }) {
  const rows = (["lint", "build", "validator"] as const).map((name) => ({
    name,
    ...metrics.gates[name],
  }));
  return (
    <div className="space-y-3">
      {rows.map((r) => {
        const total = r.pass + r.fail + r.skipped;
        const seg = (n: number) => (total ? (n / total) * 100 : 0);
        return (
          <div key={r.name}>
            <div className="mb-1 flex items-baseline justify-between text-[11.5px]">
              <span className="font-medium capitalize text-slate-300">
                {r.name}
              </span>
              <span className="text-slate-500" style={{ fontVariantNumeric: "tabular-nums" }}>
                ✓ {r.pass} pass · ✗ {r.fail} fail · – {r.skipped} skipped
              </span>
            </div>
            <div className="flex h-3 w-full gap-[2px] overflow-hidden rounded-full">
              {total === 0 ? (
                <div className="h-full w-full bg-white/[0.04]" />
              ) : (
                <>
                  {r.pass > 0 && (
                    <div style={{ width: `${seg(r.pass)}%`, background: STATUS_GOOD }} />
                  )}
                  {r.fail > 0 && (
                    <div style={{ width: `${seg(r.fail)}%`, background: STATUS_BAD }} />
                  )}
                  {r.skipped > 0 && (
                    <div style={{ width: `${seg(r.skipped)}%`, background: STATUS_SKIP, opacity: 0.55 }} />
                  )}
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function StatTile({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-white/[0.08] bg-panel px-4 py-3 shadow-card">
      <div className="text-[11px] font-medium text-slate-500">{label}</div>
      <div className="mt-0.5 font-display text-[22px] font-semibold leading-tight text-slate-100">
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-slate-500">{sub}</div>}
    </div>
  );
}

