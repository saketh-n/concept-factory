"""Persistent per-run instrumentation for Concept Factory.

Every agent run (plan / refine / consolidate / build / improve) gets a
directory under ``backend/runs/<run_id>/`` holding three artifacts:

- ``run.json``      — the structured metrics record (time, tokens, cost,
                      model, turns/tool calls, gate outcomes, retries…).
                      Updated while the run is live, final on completion.
- ``events.ndjson`` — every raw stream event from the CLI, verbatim, so a
                      session can be replayed or debugged in another tool.
- ``log.txt``       — the human-readable coalesced log lines (same lines
                      the dashboard streams live).

Disk is the source of truth: the in-memory index is just a cache rebuilt
from ``run.json`` files on startup, so records survive restarts and can be
copied elsewhere as a backup by syncing the ``runs/`` folder.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

RUNS_DIR = Path(__file__).parent / "runs"
RUNS_DIR.mkdir(exist_ok=True)

# xAI reports cost_in_usd_ticks; 1e9 ticks ≈ $1.00 (matches agent.py).
_USD_TICKS_PER_DOLLAR = 1_000_000_000

# How often (seconds) a live run.json is rewritten while events stream in.
_FLUSH_INTERVAL = 1.5

# Runs are small JSON files; cap the events a single API page returns.
EVENTS_PAGE_CAP = 2000

_index_lock = threading.Lock()
_index: Optional[Dict[str, dict]] = None  # run_id -> run record (summary cache)


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _new_record(meta: dict) -> dict:
    now = time.time()
    return {
        "id": "run_" + uuid.uuid4().hex[:12],
        "kind": meta.get("kind") or "run",
        "topicId": meta.get("topicId") or "",
        "slug": meta.get("slug") or "",
        "title": meta.get("title") or "",
        "driver": meta.get("driver") or "",
        "driverLabel": meta.get("driverLabel") or "",
        "model": meta.get("model") or "",
        "effort": meta.get("effort") or "",
        "permissionMode": meta.get("permissionMode") or "",
        "status": "running",
        "error": "",
        "sessionId": "",
        "startedAt": now,
        "startedAtIso": _iso(now),
        "endedAt": None,
        "endedAtIso": None,
        "durationSeconds": None,
        "tokensIn": 0,
        "tokensOut": 0,
        "cacheReadTokens": 0,
        "cacheCreationTokens": 0,
        "totalTokens": 0,
        "costUsd": None,
        "turns": 0,
        "toolCalls": 0,
        "retries": 0,
        "attempts": 1,
        "exitCode": None,
        "eventCount": 0,
        "logLines": 0,
        "gates": {
            "lint": {"status": "skipped", "detail": ""},
            "build": {"status": "skipped", "detail": ""},
            "validator": {"status": "skipped", "detail": ""},
        },
    }


def _load_index() -> Dict[str, dict]:
    """Lazily rebuild the id -> record cache from run.json files on disk."""
    global _index
    with _index_lock:
        if _index is not None:
            return _index
        idx: Dict[str, dict] = {}
        for meta_file in RUNS_DIR.glob("*/run.json"):
            try:
                rec = json.loads(meta_file.read_text())
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            if isinstance(rec, dict) and rec.get("id"):
                # A record still marked running after a restart is orphaned —
                # its subprocess died with the server.
                if rec.get("status") == "running":
                    rec["status"] = "error"
                    rec["error"] = rec.get("error") or "orphaned (server restarted mid-run)"
                    try:
                        meta_file.write_text(json.dumps(rec, indent=2) + "\n")
                    except OSError:
                        pass
                idx[rec["id"]] = rec
        _index = idx
        return _index


def _index_put(rec: dict) -> None:
    idx = _load_index()
    with _index_lock:
        idx[rec["id"]] = rec


class RunRecorder:
    """Collects one agent run's stream events, log lines, and metrics.

    Thread-safe: the driver thread pushes events/lines while API readers list
    runs from the index. Metric extraction is defensive — both Grok's
    ``streaming-json`` and Claude Code's ``stream-json`` shapes are handled,
    and unknown events still land in events.ndjson for later analysis.
    """

    def __init__(self, meta: dict) -> None:
        self.record = _new_record(meta)
        self.id = self.record["id"]
        self.dir = RUNS_DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._events_fh = (self.dir / "events.ndjson").open("a", encoding="utf-8")
        self._log_fh = (self.dir / "log.txt").open("a", encoding="utf-8")
        self._last_flush = 0.0
        # Per-attempt usage snapshot for Grok (its usage blocks are cumulative
        # within an attempt); folded into totals at attempt end.
        self._attempt_usage: dict = {}
        # Turns observed from assistant events — fallback when the CLI is
        # killed before it emits a final result with num_turns.
        self._turns_observed = 0
        self._turns_reported = 0
        self._flush(force=True)

    # -- artifacts -----------------------------------------------------------
    def line(self, text: str) -> None:
        """Append one human-readable log line (mirrors the live UI stream)."""
        stamp = time.strftime("%H:%M:%S", time.localtime())
        with self._lock:
            try:
                self._log_fh.write(f"[{stamp}] {text}\n")
                self._log_fh.flush()
            except (OSError, ValueError):
                pass
            self.record["logLines"] += 1

    def event(self, evt: Any) -> None:
        """Persist one raw stream event and fold its metrics into the record."""
        with self._lock:
            try:
                self._events_fh.write(json.dumps(evt, ensure_ascii=False) + "\n")
                self._events_fh.flush()
            except (OSError, ValueError, TypeError):
                pass
            self.record["eventCount"] += 1
            if isinstance(evt, dict):
                self._extract(evt)
            self._flush()

    # -- metric extraction ---------------------------------------------------
    def _extract(self, evt: dict) -> None:
        rec = self.record
        etype = evt.get("type")

        sid = evt.get("session_id") or evt.get("sessionId")
        if sid:
            rec["sessionId"] = str(sid)

        # Claude Code: system/init announces the resolved model.
        if etype == "system" and evt.get("subtype") == "init":
            if evt.get("model"):
                rec["model"] = str(evt["model"])

        # Claude Code: assistant messages → turns observed + tool_use blocks.
        if etype == "assistant":
            self._turns_observed += 1
            msg = evt.get("message") or {}
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        rec["toolCalls"] += 1

        # Grok: tool events (shape varies across CLI versions — be liberal).
        if etype in ("tool_call", "tool_use", "toolCall"):
            rec["toolCalls"] += 1

        # Claude Code: final result event carries authoritative usage/cost.
        if etype == "result":
            usage = evt.get("usage") or {}
            if isinstance(usage, dict):
                rec["tokensIn"] += int(usage.get("input_tokens") or 0)
                rec["tokensOut"] += int(usage.get("output_tokens") or 0)
                rec["cacheReadTokens"] += int(usage.get("cache_read_input_tokens") or 0)
                rec["cacheCreationTokens"] += int(
                    usage.get("cache_creation_input_tokens") or 0
                )
            cost = evt.get("total_cost_usd")
            if isinstance(cost, (int, float)):
                rec["costUsd"] = round((rec["costUsd"] or 0.0) + float(cost), 6)
            turns = evt.get("num_turns")
            if isinstance(turns, int) and turns > 0:
                self._turns_reported += turns

        # Grok: usage snapshots (cumulative within an attempt) on any event.
        usage = evt.get("usage")
        if etype != "result" and isinstance(usage, dict) and usage:
            self._attempt_usage = usage

        self._recompute_totals()

    def _fold_attempt_usage(self) -> None:
        """Add the current attempt's (cumulative) Grok usage into the totals."""
        u, self._attempt_usage = self._attempt_usage, {}
        if not u:
            return
        rec = self.record

        def _n(*keys: str) -> int:
            for k in keys:
                v = u.get(k)
                if isinstance(v, (int, float)):
                    return int(v)
            return 0

        rec["tokensIn"] += _n("prompt_tokens", "input_tokens", "promptTokens")
        rec["tokensOut"] += _n("completion_tokens", "output_tokens", "completionTokens")
        rec["cacheReadTokens"] += _n("cached_prompt_text_tokens", "cache_read_input_tokens")
        ticks = _n("cost_in_usd_ticks", "costInUsdTicks")
        if ticks:
            rec["costUsd"] = round(
                (rec["costUsd"] or 0.0) + ticks / _USD_TICKS_PER_DOLLAR, 6
            )

    def _recompute_totals(self) -> None:
        rec = self.record
        rec["turns"] = self._turns_reported or self._turns_observed
        rec["totalTokens"] = (
            rec["tokensIn"]
            + rec["tokensOut"]
            + rec["cacheReadTokens"]
            + rec["cacheCreationTokens"]
        )

    # -- lifecycle -----------------------------------------------------------
    def update(self, **fields: Any) -> None:
        """Merge top-level fields into the record (driver, model, …)."""
        with self._lock:
            for k, v in fields.items():
                if v is not None:
                    self.record[k] = v
            self._flush(force=True)

    def retry(self) -> None:
        """A resume/fallback retry happened — new attempt starts now."""
        with self._lock:
            self._fold_attempt_usage()
            self.record["retries"] += 1
            self.record["attempts"] += 1
            self._flush(force=True)

    def set_gate(self, name: str, result: dict) -> None:
        """Record one verification gate outcome (lint / build / validator)."""
        with self._lock:
            gates = self.record.setdefault("gates", {})
            gates[name] = result
            self._flush(force=True)

    def finish(
        self,
        status: str,
        error: str = "",
        exit_code: Optional[int] = None,
    ) -> dict:
        with self._lock:
            self._fold_attempt_usage()
            self._recompute_totals()
            rec = self.record
            now = time.time()
            rec["status"] = status
            rec["error"] = error or ""
            rec["endedAt"] = now
            rec["endedAtIso"] = _iso(now)
            rec["durationSeconds"] = round(now - rec["startedAt"], 3)
            if exit_code is not None:
                rec["exitCode"] = exit_code
            self._flush(force=True)
            for fh in (self._events_fh, self._log_fh):
                try:
                    fh.close()
                except (OSError, ValueError):
                    pass
            return dict(rec)

    def _flush(self, force: bool = False) -> None:
        """Write run.json (throttled while streaming) and refresh the index.

        Callers hold self._lock.
        """
        now = time.time()
        if not force and (now - self._last_flush) < _FLUSH_INTERVAL:
            return
        self._last_flush = now
        try:
            tmp = self.dir / "run.json.tmp"
            tmp.write_text(json.dumps(self.record, indent=2) + "\n")
            tmp.replace(self.dir / "run.json")
        except OSError:
            pass
        _index_put(self.record)


def new_run(**meta: Any) -> RunRecorder:
    rec = RunRecorder(meta)
    _index_put(rec.record)
    return rec


# --- Read API (backend endpoints) --------------------------------------------
def get_run(run_id: str) -> Optional[dict]:
    idx = _load_index()
    with _index_lock:
        rec = idx.get(run_id)
        return dict(rec) if rec else None


def list_runs(
    topic_id: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 200,
) -> List[dict]:
    idx = _load_index()
    with _index_lock:
        # Drop ghosts whose directory was deleted externally (manual cleanup,
        # backup pruning) so the dashboard never shows unopenable runs.
        stale = [
            rid for rid, r in idx.items()
            if r.get("status") != "running" and not (RUNS_DIR / rid / "run.json").is_file()
        ]
        for rid in stale:
            del idx[rid]
        runs = [dict(r) for r in idx.values()]
    if topic_id:
        runs = [r for r in runs if r.get("topicId") == topic_id]
    if kind:
        runs = [r for r in runs if r.get("kind") == kind]
    runs.sort(key=lambda r: r.get("startedAt") or 0, reverse=True)
    return runs[: max(1, min(limit, 1000))]


def run_events(run_id: str, offset: int = 0, limit: int = EVENTS_PAGE_CAP) -> dict:
    """Parsed stream events for the viewer (paginated by line offset)."""
    path = RUNS_DIR / run_id / "events.ndjson"
    if not path.is_file():
        return {"events": [], "offset": offset, "total": 0}
    events: List[Any] = []
    total = 0
    limit = max(1, min(limit, EVENTS_PAGE_CAP))
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            total = i + 1
            if i < offset or len(events) >= limit:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"type": "raw", "data": line[:2000]})
    return {"events": events, "offset": offset, "total": total}


def run_log_text(run_id: str) -> str:
    path = RUNS_DIR / run_id / "log.txt"
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def export_run(run_id: str, fmt: str = "json") -> Optional[tuple]:
    """(filename, media_type, payload_bytes) for a downloadable export.

    ``json``   → single self-contained bundle: record + events + log.
    ``ndjson`` → the raw event stream, exactly as the CLI emitted it.
    ``txt``    → the human-readable log.
    """
    rec = get_run(run_id)
    if not rec:
        return None
    if fmt == "ndjson":
        path = RUNS_DIR / run_id / "events.ndjson"
        data = path.read_bytes() if path.is_file() else b""
        return (f"{run_id}.events.ndjson", "application/x-ndjson", data)
    if fmt == "txt":
        return (
            f"{run_id}.log.txt",
            "text/plain; charset=utf-8",
            run_log_text(run_id).encode(),
        )
    bundle = {
        "run": rec,
        "log": run_log_text(run_id).splitlines(),
        "events": run_events(run_id, 0, EVENTS_PAGE_CAP)["events"],
    }
    return (
        f"{run_id}.json",
        "application/json",
        json.dumps(bundle, indent=2, ensure_ascii=False).encode(),
    )


def metrics_summary() -> dict:
    """Aggregates for the dashboard KPI tiles and charts."""
    runs = list_runs(limit=1000)
    finished = [r for r in runs if r.get("status") in ("success", "error")]
    succeeded = [r for r in finished if r.get("status") == "success"]

    def _gate_counts(name: str) -> dict:
        counts = {"pass": 0, "fail": 0, "skipped": 0}
        for r in runs:
            status = ((r.get("gates") or {}).get(name) or {}).get("status")
            if status in counts:
                counts[status] += 1
            elif status:
                counts["fail"] += 1
        return counts

    validator_rates = [
        ((r.get("gates") or {}).get("validator") or {}).get("passRate")
        for r in runs
    ]
    validator_rates = [v for v in validator_rates if isinstance(v, (int, float))]

    durations = [
        r["durationSeconds"] for r in finished if r.get("durationSeconds") is not None
    ]
    by_model: Dict[str, dict] = {}
    for r in runs:
        key = f"{r.get('driver') or '?'}/{r.get('model') or 'default'}"
        b = by_model.setdefault(
            key,
            {"runs": 0, "costUsd": 0.0, "tokens": 0, "success": 0, "finished": 0},
        )
        b["runs"] += 1
        b["costUsd"] = round(b["costUsd"] + (r.get("costUsd") or 0.0), 6)
        b["tokens"] += r.get("totalTokens") or 0
        if r.get("status") in ("success", "error"):
            b["finished"] += 1
            if r.get("status") == "success":
                b["success"] += 1

    return {
        "totalRuns": len(runs),
        "running": sum(1 for r in runs if r.get("status") == "running"),
        "succeeded": len(succeeded),
        "failed": len(finished) - len(succeeded),
        "successRate": round(len(succeeded) / len(finished), 4) if finished else None,
        "totalCostUsd": round(sum(r.get("costUsd") or 0.0 for r in runs), 6),
        "totalTokensIn": sum(r.get("tokensIn") or 0 for r in runs),
        "totalTokensOut": sum(r.get("tokensOut") or 0 for r in runs),
        "totalTokens": sum(r.get("totalTokens") or 0 for r in runs),
        "totalToolCalls": sum(r.get("toolCalls") or 0 for r in runs),
        "totalRetries": sum(r.get("retries") or 0 for r in runs),
        "avgDurationSeconds": (
            round(sum(durations) / len(durations), 3) if durations else None
        ),
        "gates": {
            "lint": _gate_counts("lint"),
            "build": _gate_counts("build"),
            "validator": _gate_counts("validator"),
        },
        "avgValidatorPassRate": (
            round(sum(validator_rates) / len(validator_rates), 4)
            if validator_rates
            else None
        ),
        "byModel": by_model,
    }


def reset_cache_for_tests() -> None:
    """Drop the in-memory index so tests with a fresh RUNS_DIR start clean."""
    global _index
    with _index_lock:
        _index = None
