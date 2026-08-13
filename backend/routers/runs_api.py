"""Run instrumentation API: metrics, list, detail, export."""


from __future__ import annotations


from typing import Optional


from fastapi import APIRouter, HTTPException


from fastapi.responses import Response


import runs


router = APIRouter()


# --- Run instrumentation (persisted per-run logs + metrics) ------------------
@router.get("/api/runs/metrics")
def run_metrics() -> dict:
    """Aggregates for the metrics dashboard (KPIs, gate outcomes, per-model)."""
    return runs.metrics_summary()


@router.get("/api/runs")
def list_runs(topicId: Optional[str] = None, kind: Optional[str] = None,
              limit: int = 200) -> dict:
    """Structured per-run records, newest first."""
    return {"runs": runs.list_runs(topic_id=topicId, kind=kind, limit=limit)}


@router.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    rec = runs.get_run(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Run not found")
    return rec


@router.get("/api/runs/{run_id}/events")
def get_run_events(run_id: str, offset: int = 0, limit: int = 500) -> dict:
    """Raw stream events (the persisted session context), paginated."""
    if not runs.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return runs.run_events(run_id, offset=offset, limit=limit)


@router.get("/api/runs/{run_id}/log")
def get_run_log(run_id: str) -> dict:
    """The persisted human-readable log for this run."""
    if not runs.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return {"lines": runs.run_log_text(run_id).splitlines()}


@router.get("/api/runs/{run_id}/export")
def export_run(run_id: str, format: str = "json") -> Response:
    """Download a run for debugging in another tool.

    ``format=json`` → self-contained bundle (record + events + log);
    ``format=ndjson`` → raw event stream; ``format=txt`` → readable log.
    """
    if format not in ("json", "ndjson", "txt"):
        raise HTTPException(status_code=400, detail="format must be json|ndjson|txt")
    exported = runs.export_run(run_id, fmt=format)
    if not exported:
        raise HTTPException(status_code=404, detail="Run not found")
    filename, media_type, payload = exported
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
