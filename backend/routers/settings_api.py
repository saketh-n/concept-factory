"""Driver settings + credits API routes."""


from __future__ import annotations


import asyncio


import json


from fastapi import APIRouter, Request


from fastapi.responses import StreamingResponse


import agent


from store import BudgetUpdate, DriverSettingsUpdate


router = APIRouter()


@router.get("/api/settings")
def get_settings(syncCli: bool = False) -> dict:
    """Global Grok Build options (persisted).

    By default returns stored settings only (fast — form can paint immediately).
    Pass ``syncCli=1`` to also merge live Grok CLI current model from the catalog
    (uses the TTL cache when warm).
    """
    stored = agent.load_settings()
    if not syncCli:
        return stored
    catalog = agent.get_settings_catalog()
    return agent.apply_cli_current_to_settings(stored, catalog, follow_cli=False)


@router.get("/api/settings/current")
def get_current_models() -> dict:
    """Cheap current-model read straight from the Grok CLI config file (no spawn)."""
    return agent.read_current_models()


@router.get("/api/settings/current/stream")
async def stream_current_models(request: Request) -> StreamingResponse:
    """Server-Sent Events: push the current Grok model whenever config.toml
    changes on disk, so a `/model` switch in the terminal updates the open
    widget in real time without polling or a manual refresh."""

    async def gen():
        last_sig = None
        # Emit immediately on connect so the client syncs without waiting.
        yield f"data: {json.dumps(agent.read_current_models())}\n\n"
        last_sig = agent.current_models_signature()
        while True:
            if await request.is_disconnected():
                break
            sig = agent.current_models_signature()
            if sig != last_sig:
                last_sig = sig
                yield f"data: {json.dumps(agent.read_current_models())}\n\n"
            else:
                # Comment line as a keep-alive so proxies don't drop the stream.
                yield ": keep-alive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.put("/api/settings")
def put_settings(payload: DriverSettingsUpdate) -> dict:
    """Persist Grok options; jobs pick this up on next run.

    Also compiles the selection into ``~/.grok/config.toml`` default so the
    interactive Grok CLI agrees with the widget. Disable with CF_SETTINGS_SYNC_CLI=0.
    """
    current = agent.load_settings()
    patch = payload.model_dump(exclude_none=True)
    # driver patches are ignored — normalize_settings forces Grok-only.
    if "grok" in patch and isinstance(patch["grok"], dict):
        current.setdefault("grok", {}).update(patch["grok"])
    saved = agent.save_settings(current)
    saved["cliSync"] = agent.sync_settings_to_cli(saved)
    return saved


@router.get("/api/settings/catalog")
def get_settings_catalog(force: bool = False) -> dict:
    """Live-discovered Grok dropdown options (TTL-cached; ``force=1`` re-polls)."""
    return agent.get_settings_catalog(force=force)


@router.get("/api/settings/bootstrap")
def bootstrap_settings() -> dict:
    """Optional combined poll: catalog + settings with live CLI models.

    The modal prefers parallel GET /settings + GET /catalog so a missing
    bootstrap route (older server) still loads. This endpoint remains for
    clients that want a single round-trip.
    """
    catalog = agent.get_settings_catalog()
    settings = agent.apply_cli_current_to_settings(
        agent.load_settings(), catalog, follow_cli=True
    )
    return {"catalog": catalog, "settings": settings}


@router.post("/api/settings/catalog/refresh")
def refresh_settings_catalog() -> dict:
    """Bust TTL and re-poll CLIs.

    Returns both the catalog and settings with models synced to live CLI
    current (so the modal can update the selected model on refresh).
    """
    catalog = agent.get_settings_catalog(force=True)
    settings = agent.apply_cli_current_to_settings(
        agent.load_settings(), catalog, follow_cli=True
    )
    return {"catalog": catalog, "settings": settings}


@router.get("/api/credits")
def get_credits(force: bool = False) -> dict:
    """Live prepaid $ remaining from console.x.ai (Management API)."""
    return agent.get_balance(force=force)


@router.put("/api/credits/budget")
def set_credit_budget(payload: BudgetUpdate) -> dict:
    """No-op: remaining balance is owned by console.x.ai, not a local budget."""
    return agent.set_budget_usd(payload.budgetUsd)
