import React, { useEffect, useRef, useState } from "react";

/**
 * Chart primitives for the runs dashboard.
 *
 * Colors are validated for CVD + contrast against the #10151f panel:
 * series-1 blue / series-2 green for identity, status colors strictly for
 * pass/fail and always paired with a ✓/✗/– glyph, never color alone.
 */
export const SERIES_1 = "#3987e5"; // blue — single-series magnitude, token input
export const SERIES_2 = "#008300"; // green — token output
export const STATUS_GOOD = "#0ca30c";
export const STATUS_BAD = "#d03b3b";
export const STATUS_SKIP = "#898781";
export const GRID = "rgba(255,255,255,0.06)";
export const BASELINE = "rgba(255,255,255,0.16)";

/** Measured width of a container so SVG charts render crisp at any size. */
export function useMeasure<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setW(e.contentRect.width);
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** ~3 clean axis ticks covering [0, max]. */
export function niceTicks(max: number): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / 2.5;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? 10 * pow;
  const ticks: number[] = [];
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(v);
  if (ticks[ticks.length - 1] < max) ticks.push(ticks.length * step);
  return ticks;
}

/** Bar with a 4px rounded data-end, square at the baseline. */
export function barPath(x: number, yTop: number, w: number, h: number): string {
  if (h <= 0) return "";
  const r = Math.min(4, w / 2, h);
  return [
    `M${x},${yTop + h}`,
    `v${-(h - r)}`,
    `q0,${-r} ${r},${-r}`,
    `h${w - 2 * r}`,
    `q${r},0 ${r},${r}`,
    `v${h - r}`,
    "z",
  ].join("");
}

// --- charts ---------------------------------------------------------------------
export interface BarPoint {
  key: string;
  value: number;
  /** Second (stacked) segment value, drawn above `value` with a 2px gap. */
  value2?: number;
  tooltip: string[];
}

/** Vertical bar chart (single series, or stacked pair when value2 is set). */
export function Bars({
  points,
  yFmt,
  height = 148,
  stackedLabels,
}: {
  points: BarPoint[];
  yFmt: (v: number) => string;
  height?: number;
  /** Legend labels [series1, series2] — only for the stacked variant. */
  stackedLabels?: [string, string];
}) {
  const [wrapRef, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const PAD_L = 40;
  const PAD_B = 18;
  const PAD_T = 8;
  const plotW = Math.max(0, width - PAD_L - 6);
  const plotH = height - PAD_B - PAD_T;
  const max = Math.max(1e-9, ...points.map((p) => p.value + (p.value2 ?? 0)));
  const ticks = niceTicks(max);
  const yMax = ticks[ticks.length - 1];
  const band = points.length ? plotW / points.length : plotW;
  const barW = Math.max(2, Math.min(24, band - 2));
  const y = (v: number) => PAD_T + plotH * (1 - v / yMax);

  return (
    <div ref={wrapRef} className="relative">
      {stackedLabels && (
        <div className="mb-1.5 flex items-center gap-4 text-[11px] text-slate-400">
          {[SERIES_1, SERIES_2].map((c, i) => (
            <span key={c} className="flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-[3px]"
                style={{ background: c }}
              />
              {stackedLabels[i]}
            </span>
          ))}
        </div>
      )}
      {width > 0 && (
        <svg width={width} height={height} role="img">
          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={PAD_L}
                x2={width - 4}
                y1={y(t)}
                y2={y(t)}
                stroke={t === 0 ? BASELINE : GRID}
                strokeWidth={1}
              />
              <text
                x={PAD_L - 6}
                y={y(t) + 3}
                textAnchor="end"
                fontSize={9.5}
                fill="#898781"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {yFmt(t)}
              </text>
            </g>
          ))}
          {points.map((p, i) => {
            const x = PAD_L + i * band + (band - barW) / 2;
            const h1 = (p.value / yMax) * plotH;
            const h2 = ((p.value2 ?? 0) / yMax) * plotH;
            return (
              <g key={p.key} opacity={hover === null || hover === i ? 1 : 0.45}>
                <path d={barPath(x, y(p.value), barW, h1)} fill={SERIES_1} />
                {h2 > 0.5 && (
                  // stacked segment, separated by a 2px surface gap
                  <path
                    d={barPath(x, y(p.value + (p.value2 ?? 0)) - 2, barW, h2)}
                    fill={SERIES_2}
                  />
                )}
                <rect
                  x={PAD_L + i * band}
                  y={PAD_T}
                  width={band}
                  height={plotH + PAD_B}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                />
              </g>
            );
          })}
          {points.length > 0 && (
            <>
              <text x={PAD_L} y={height - 4} fontSize={9.5} fill="#898781">
                oldest
              </text>
              <text
                x={width - 4}
                y={height - 4}
                textAnchor="end"
                fontSize={9.5}
                fill="#898781"
              >
                latest
              </text>
            </>
          )}
        </svg>
      )}
      {hover !== null && points[hover] && width > 0 && (
        <div
          className="pointer-events-none absolute z-10 rounded-lg border border-white/10 bg-[#0c1017] px-2.5 py-1.5 text-[11px] leading-relaxed text-slate-300 shadow-pop"
          style={{
            left: Math.min(
              Math.max(0, PAD_L + hover * band - 40),
              Math.max(0, width - 170)
            ),
            top: -6,
            transform: "translateY(-100%)",
          }}
        >
          {points[hover].tooltip.map((line, i) => (
            <div key={i} className={i === 0 ? "font-medium text-slate-100" : ""}>
              {line}
            </div>
          ))}
        </div>
      )}
      {points.length === 0 && (
        <div
          className="grid place-items-center text-[12px] text-slate-600"
          style={{ height }}
        >
          no data yet
        </div>
      )}
    </div>
  );
}

