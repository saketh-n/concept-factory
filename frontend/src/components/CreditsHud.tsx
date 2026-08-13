import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Credits } from "../api";
import { usePolling } from "../hooks/usePolling";
import { IconRefresh } from "./icons";

/**
 * Live dollar credit balance from console.x.ai (Management API prepaid).
 * Draggable so it never permanently obscures the board.
 */

const POS_KEY = "cf-credits-hud-pos";

function toneOf(c: Credits | null): "ok" | "warn" | "low" {
  if (!c || c.ok === false) return "low";
  if (c.pct != null) {
    if (c.pct <= 12) return "low";
    if (c.pct <= 30) return "warn";
    return "ok";
  }
  if (c.remainingUsd != null && c.remainingUsd < 0) return "low";
  return "ok";
}

const DOT: Record<string, string> = {
  ok: "bg-emerald-400 shadow-[0_0_0_3px_rgba(52,211,153,0.22)]",
  warn: "bg-amber-400 shadow-[0_0_0_3px_rgba(251,191,36,0.22)]",
  low: "bg-rose-400 shadow-[0_0_0_3px_rgba(248,113,113,0.22)] animate-pulse",
};

const BAR: Record<string, string> = {
  ok: "from-emerald-400 to-violet-400",
  warn: "from-amber-400 to-orange-400",
  low: "from-rose-400 to-amber-400",
};

type Pos = { x: number; y: number };

function loadPos(): Pos | null {
  try {
    const raw = localStorage.getItem(POS_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as Pos;
    if (typeof p?.x === "number" && typeof p?.y === "number") return p;
  } catch {
    /* ignore */
  }
  return null;
}

function clampPos(x: number, y: number, w: number, h: number): Pos {
  const maxX = Math.max(8, window.innerWidth - w - 8);
  const maxY = Math.max(8, window.innerHeight - h - 8);
  return {
    x: Math.min(maxX, Math.max(8, x)),
    y: Math.min(maxY, Math.max(8, y)),
  };
}

export default function CreditsHud({
  variant = "header",
}: {
  /** header = in-flow in the sticky bar until dragged; floating = always free */
  variant?: "header" | "floating";
}) {
  const [credits, setCredits] = useState<Credits | null>(null);
  const [pos, setPos] = useState<Pos | null>(() => loadPos());
  const [dragging, setDragging] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    startX: number;
    startY: number;
    origX: number;
    origY: number;
    moved: boolean;
  } | null>(null);

  const refresh = useCallback((force = false) => {
    api
      .getCredits(force)
      .then(setCredits)
      .catch(() =>
        setCredits({
          ok: false,
          currency: "USD",
          label: "Balance offline",
          detail: "Couldn't reach backend",
          spentUsd: 0,
          sessionSpendUsd: 0,
          budgetUsd: null,
          remainingUsd: null,
          pct: null,
          error: "network",
        })
      );
  }, []);

  usePolling(() => refresh(false), 15000, { immediate: true });

  // Keep on-screen after resize.
  useEffect(() => {
    const onResize = () => {
      setPos((p) => {
        if (!p || !rootRef.current) return p;
        const r = rootRef.current.getBoundingClientRect();
        const next = clampPos(p.x, p.y, r.width, r.height);
        localStorage.setItem(POS_KEY, JSON.stringify(next));
        return next;
      });
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    // Don't start a drag from the refresh button.
    if ((e.target as HTMLElement).closest("button")) return;
    const el = rootRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    // First drag: pin current screen position (even if still in-flow header).
    const origin = pos ?? { x: r.left, y: r.top };
    if (!pos) setPos(origin);
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origX: origin.x,
      origY: origin.y,
      moved: false,
    };
    setDragging(true);
    el.setPointerCapture(e.pointerId);
    e.preventDefault();
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    const el = rootRef.current;
    if (!d || !el) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    const r = el.getBoundingClientRect();
    const next = clampPos(d.origX + dx, d.origY + dy, r.width, r.height);
    setPos(next);
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const d = dragRef.current;
    dragRef.current = null;
    setDragging(false);
    if (d?.moved && pos) {
      localStorage.setItem(POS_KEY, JSON.stringify(pos));
    }
    try {
      rootRef.current?.releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };

  const resetPos = (e: React.MouseEvent) => {
    e.stopPropagation();
    localStorage.removeItem(POS_KEY);
    setPos(null);
  };

  const tone = toneOf(credits);
  const pct = credits?.pct;
  const free = pos != null || variant === "floating";

  const shell = free
    ? "fixed z-50 max-w-[min(300px,calc(100vw-28px))]"
    : "relative shrink-0 max-w-[160px]";

  const style: React.CSSProperties | undefined = free
    ? {
        left: pos?.x ?? 14,
        top: pos?.y ?? 14,
        cursor: dragging ? "grabbing" : "grab",
        touchAction: "none",
      }
    : { cursor: "grab", touchAction: "none" };

  return (
    <div
      ref={rootRef}
      className={`${shell} flex select-none items-center gap-2.5 rounded-xl border border-white/10 bg-well/90 px-3 py-1.5 text-slate-200 shadow-card backdrop-blur-md ${
        dragging ? "border-emerald-400/40 shadow-pop" : ""
      }`}
      style={style}
      title={
        (credits?.detail || "Credits from console.x.ai") + " · drag to move"
      }
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onDoubleClick={resetPos}
    >
      <span
        className={`h-2 w-2 shrink-0 rounded-full ${DOT[tone]}`}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[12px] font-semibold leading-tight tabular-nums text-slate-100">
          {credits?.label ?? "Loading…"}
        </div>
        {free ? (
          <>
            {pct != null && (
              <div
                className="mt-1 h-1 overflow-hidden rounded-full bg-white/[0.08]"
                title={`${pct}% of prepaid left`}
              >
                <div
                  className={`h-full rounded-full bg-gradient-to-r ${BAR[tone]} transition-all duration-500`}
                  style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
                />
              </div>
            )}
            <div className="mt-0.5 truncate font-mono text-[9.5px] text-slate-500">
              {credits?.detail ?? "Fetching…"}
            </div>
          </>
        ) : (
          pct != null && (
            <div
              className="mt-[3px] h-[3px] w-full max-w-[72px] overflow-hidden rounded-full bg-white/[0.08]"
              title={`${pct}% of prepaid left`}
            >
              <div
                className={`h-full rounded-full bg-gradient-to-r ${BAR[tone]} transition-all duration-500`}
                style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
              />
            </div>
          )
        )}
      </div>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          refresh(true);
        }}
        onPointerDown={(e) => e.stopPropagation()}
        className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-white/[0.06] text-slate-400 transition hover:bg-white/10 hover:text-slate-200"
        title="Refresh from console.x.ai"
      >
        <IconRefresh size={11} />
      </button>
    </div>
  );
}
