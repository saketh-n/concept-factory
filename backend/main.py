"""Concept Factory backend — FastAPI app assembly.

State models and persistence live in ``store``, background agent jobs in
``jobs``, and the HTTP surface in ``routers/``. This module only wires the
app together, so ``uvicorn main:app`` keeps working unchanged.
"""
from __future__ import annotations

import os
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import agent
from jobs import _run_verification_gates, _start_run  # noqa: F401 — re-exported for tests
from routers import concepts, runs_api, settings_api, topics

app = FastAPI(title="Concept Factory")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _warm_settings_catalog() -> None:
    """Pre-poll the settings catalog in the background at boot.

    Discovery costs ~1s cold (CLI process startup dominates), so pay it
    while the server is idle instead of on first modal open. Disable with
    CF_SETTINGS_WARM=0 (tests do this).
    """
    if os.environ.get("CF_SETTINGS_WARM", "1").strip().lower() in ("0", "false", "no", "off"):
        return

    def _warm() -> None:
        try:
            agent.get_settings_catalog()
        except Exception:  # noqa: BLE001 — warm is best-effort
            pass

    threading.Thread(target=_warm, daemon=True, name="cf-catalog-warm").start()


app.include_router(topics.router)
app.include_router(settings_api.router)
app.include_router(runs_api.router)
app.include_router(concepts.router)
