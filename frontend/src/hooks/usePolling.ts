import { useEffect, useRef } from "react";

/**
 * Run `fn` every `intervalMs` milliseconds. Pass `null` (or 0) to pause.
 *
 * - `immediate` fires one tick as soon as polling (re)starts.
 * - `restartKey` restarts the timer (and the immediate tick) when it changes,
 *   e.g. a slug/topic id whose change should refresh right away.
 *
 * The latest `fn` is always called (kept in a ref), so callers don't need to
 * memoize it and the timer isn't reset on every render.
 */
export function usePolling(
  fn: () => void | Promise<void>,
  intervalMs: number | null,
  opts: { immediate?: boolean; restartKey?: unknown } = {}
) {
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const immediate = opts.immediate ?? false;

  useEffect(() => {
    if (!intervalMs) return;
    if (immediate) void fnRef.current();
    const id = window.setInterval(() => void fnRef.current(), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs, immediate, opts.restartKey]);
}
