"""Concept Factory backend.

A tiny FastAPI service that persists a meta prompt and a list of topic cards
to a JSON file on disk. State is loaded on startup and written back on every
mutation, so everything survives a server restart.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

import os

import agent
import launcher
import runs

DATA_FILE = Path(__file__).parent / "data.json"
_lock = threading.Lock()

# Plan lifecycle: none -> queued -> planning -> ready -> building -> built
# (any step can land on "error"). Transient states are reset on startup.
_TRANSIENT = {"queued", "planning", "building"}

# Live progress streamed from each Grok run, kept in memory only (not
# persisted — it's ephemeral job output). topic_id -> list[str] of log lines.
_LOGS: dict = {}
_LOGS_LOCK = threading.Lock()
_LOG_CAP = 500

# Per-concept tutor chat history (slug -> [{role, content}, ...]). Ephemeral —
# cleared on server restart. System prompt is rebuilt each turn, not stored.
_CHAT: dict = {}
_CHAT_LOCK = threading.Lock()
_CHAT_CAP = 40  # max user+assistant turns kept (system is separate)


def _log_reset(topic_id: str) -> None:
    with _LOGS_LOCK:
        _LOGS[topic_id] = []


def _log_append(topic_id: str, line: str) -> None:
    with _LOGS_LOCK:
        buf = _LOGS.setdefault(topic_id, [])
        buf.append(line)
        if len(buf) > _LOG_CAP:
            del buf[: len(buf) - _LOG_CAP]


def _log_get(topic_id: str) -> list:
    with _LOGS_LOCK:
        return list(_LOGS.get(topic_id, []))


def _start_run(kind: str, topic_id: str, slug: str, title: str):
    """Create a persisted run record + an emitter that feeds both the live
    in-memory log (dashboard stream) and the run's on-disk log.txt.

    ``source=concept-factory`` marks the run as app-invoked so the metrics
    dashboard lists it; ad-hoc ``runs.new_run`` calls without that source are
    never shown as if they were user agent sessions.
    """
    recorder = runs.new_run(
        kind=kind,
        topicId=topic_id,
        slug=slug,
        title=title,
        source=runs.SOURCE_APP,
    )

    def emit(line: str) -> None:
        _log_append(topic_id, line)
        recorder.line(line)

    return recorder, emit


def _run_verification_gates(recorder, cwd: Path, emit, build_ok: bool) -> None:
    """Harness-side gates after a build/improve run: build result (already
    known from finalize_build), then lint, then the level validator."""
    recorder.set_gate(
        "build",
        {"status": "pass" if build_ok else "fail",
         "detail": "" if build_ok else "servable bundle failed to compile"},
    )
    if not build_ok:
        recorder.set_gate("lint", {"status": "skipped", "detail": "build failed"})
        recorder.set_gate("validator", {"status": "skipped", "detail": "build failed"})
        return
    recorder.set_gate("lint", agent.run_lint_gate(cwd, emit))
    recorder.set_gate("validator", agent.run_validator_gate(cwd, emit))


# --- Models -----------------------------------------------------------------
class Topic(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    title: str = ""
    blurb: str = ""
    notes: str = ""
    slug: str = ""
    planStatus: str = "none"
    plan: str = ""
    sessionId: str = ""
    planError: str = ""
    fullstack: bool = False  # runs its own backend; launched, not statically served
    reviewed: bool = False  # human has reviewed the built concept; only meaningful once built
    # Hierarchy as a materialized path, e.g. ["Linux", "Shell"]. Groups are
    # derived from these — no separate folder entities exist anywhere.
    path: List[str] = Field(default_factory=list)


class TopicCreate(BaseModel):
    title: str


class BulkCreate(BaseModel):
    text: str


class TopicUpdate(BaseModel):
    title: Optional[str] = None
    blurb: Optional[str] = None
    notes: Optional[str] = None
    reviewed: Optional[bool] = None
    path: Optional[List[str]] = None


class MetaPromptUpdate(BaseModel):
    metaPrompt: str


class ConsolidateRequest(BaseModel):
    ids: List[str]


class State(BaseModel):
    metaPrompt: str = ""
    topics: List[Topic] = Field(default_factory=list)


# --- Persistence ------------------------------------------------------------
def _reconcile(topic: Topic) -> str:
    """Derive a topic's plan status from what's actually on disk.

    The workspace is the source of truth: a built bundle means "built"
    regardless of the stored enum, and a transient/stale status with no bundle
    means the job died (its subprocess can't be resumed after a restart), so we
    fall back to whether a plan survived. This keeps status from silently
    drifting away from reality across restarts.
    """
    if topic.fullstack:
        return topic.planStatus  # launched on demand, not backed by a dist/
    if agent.is_built(topic.slug):
        # Auto-heal bundles built with the wrong base (externally-prebuilt
        # concepts never went through finalize_build; a failed improve can
        # also leave root-based assets behind). Rebuild so assets resolve
        # under /concepts/<slug>/ instead of 404-ing.
        if not agent.dist_base_ok(topic.slug):
            agent.finalize_build(
                agent.topic_dir(topic.slug),
                f"/concepts/{topic.slug}/",
                lambda _l: None,
            )
        return "built"
    # No bundle on disk: any mid-flight or stale "built" status is orphaned.
    if topic.planStatus in _TRANSIENT or topic.planStatus == "built":
        return "ready" if topic.plan else "none"
    return topic.planStatus  # ready / error / none are already disk-consistent


def _import_prebuilt(loaded: State) -> bool:
    """Register externally-copied, pre-built concepts as cards.

    Any workspace folder holding a ``concept.json`` marker plus a built
    ``dist/`` (e.g. repos copied in from the sister ``software-engineering``
    project) becomes a "built" topic if it isn't one already. Slug = folder
    name, so it maps straight to the /concepts/<slug>/ serving route. Agent-built
    concepts have no concept.json, so they are never double-registered.
    """
    known = {t.slug for t in loaded.topics if t.slug}
    added = False
    for marker in sorted(agent.WORKSPACE.glob("*/concept.json")):
        slug = marker.parent.name
        if slug in known or not agent.is_built(slug):
            continue
        try:
            meta = json.loads(marker.read_text())
        except (json.JSONDecodeError, ValueError):
            meta = {}
        loaded.topics.append(Topic(
            title=meta.get("title") or slug.replace("-", " ").title(),
            blurb=meta.get("blurb", ""),
            slug=slug,
            planStatus="built",
        ))
        known.add(slug)
        added = True
    return added


def _register_fullstack(loaded: State) -> bool:
    """Ensure each full-stack concept exists and is flagged full-stack.

    Upgrades an existing topic with a matching slug (e.g. one left over from an
    earlier static registration) rather than skipping it — otherwise such a
    topic gets stranded as a non-clickable "none" card.
    """
    by_slug = {t.slug: t for t in loaded.topics if t.slug}
    changed = False
    for slug, spec in launcher.SPECS.items():
        existing = by_slug.get(slug)
        if existing is None:
            loaded.topics.append(Topic(
                title=spec["title"],
                blurb=spec.get("blurb", ""),
                slug=slug,
                planStatus="built",
                fullstack=True,
            ))
            changed = True
        elif not existing.fullstack:
            existing.fullstack = True
            existing.planStatus = "built"
            if not existing.blurb:
                existing.blurb = spec.get("blurb", "")
            changed = True
    return changed


def load_state() -> State:
    if DATA_FILE.exists():
        try:
            loaded = State(**json.loads(DATA_FILE.read_text()))
            changed = False
            for topic in loaded.topics:
                reconciled = _reconcile(topic)
                if reconciled != topic.planStatus:
                    topic.planStatus = reconciled
                    changed = True
            changed = _import_prebuilt(loaded) or changed
            changed = _register_fullstack(loaded) or changed
            if changed:
                save_state(loaded)  # persist so disk matches reality
            return loaded
        except (json.JSONDecodeError, ValueError):
            # Corrupt file — start fresh rather than crash on boot.
            pass
    # Fresh install: still surface any pre-built / full-stack concepts on disk.
    fresh = State()
    imported = _import_prebuilt(fresh)
    registered = _register_fullstack(fresh)
    if imported or registered:
        save_state(fresh)
    return fresh


def save_state(state: State) -> None:
    DATA_FILE.write_text(json.dumps(state.model_dump(), indent=2))


# --- Topic parsing ----------------------------------------------------------
# Leading list markers we strip so pasted lists come in clean: "- ", "* ",
# "• ", "1. ", "2) ", etc. Splitting on newlines is fully deterministic, so no
# LLM is needed to separate a pasted list into individual topics.
#
# Line grammar:   [Group > Subgroup > ] Title [ | notes ]
# e.g.            Linux > Shell > Vim & Remote Editing | modal editing, ssh
_MARKER_RE = re.compile(r"^\s*(?:[-*•·‣▪]|\d+[.)])\s+")


def parse_topics(text: str) -> List[tuple[List[str], str, str]]:
    items: List[tuple[List[str], str, str]] = []
    for line in text.splitlines():
        cleaned = _MARKER_RE.sub("", line).strip()
        if not cleaned:
            continue
        head, _, notes = cleaned.partition("|")
        *path, title = [part.strip() for part in head.split(">")]
        if title:
            items.append(([p for p in path if p], title, notes.strip()))
    return items


state: State = load_state()


# --- App --------------------------------------------------------------------
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

    Discovery costs ~1s cold (Claude CLI process startup dominates), so pay it
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


@app.get("/api/state", response_model=State)
def get_state() -> State:
    return state


@app.put("/api/meta-prompt", response_model=State)
def update_meta_prompt(payload: MetaPromptUpdate) -> State:
    with _lock:
        state.metaPrompt = payload.metaPrompt
        save_state(state)
    return state


# --- Agent driver settings (Grok Build only) --------------------------------
class DriverSettingsUpdate(BaseModel):
    """Partial or full settings blob from the dashboard modal."""
    driver: Optional[str] = None  # ignored; always coerced to grok
    grok: Optional[dict] = None
    # Accepted but ignored for backward-compat with older clients.
    claude: Optional[dict] = None


@app.get("/api/settings")
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


@app.get("/api/settings/current")
def get_current_models() -> dict:
    """Cheap current-model read straight from the Grok CLI config file (no spawn)."""
    return agent.read_current_models()


@app.get("/api/settings/current/stream")
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


@app.put("/api/settings")
def put_settings(payload: DriverSettingsUpdate) -> dict:
    """Persist Grok options; jobs pick this up on next run.

    Also compiles the selection into ``~/.grok/config.toml`` default so the
    interactive Grok CLI agrees with the widget. Disable with CF_SETTINGS_SYNC_CLI=0.
    """
    current = agent.load_settings()
    patch = payload.model_dump(exclude_none=True)
    # driver / claude patches are ignored — normalize_settings forces Grok-only.
    if "grok" in patch and isinstance(patch["grok"], dict):
        current.setdefault("grok", {}).update(patch["grok"])
    saved = agent.save_settings(current)
    saved["cliSync"] = agent.sync_settings_to_cli(saved)
    return saved


@app.get("/api/settings/catalog")
def get_settings_catalog(force: bool = False) -> dict:
    """Live-discovered Grok dropdown options (TTL-cached; ``force=1`` re-polls)."""
    return agent.get_settings_catalog(force=force)


@app.get("/api/settings/bootstrap")
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


@app.post("/api/settings/catalog/refresh")
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


@app.post("/api/topics", response_model=Topic)
def create_topic(payload: TopicCreate) -> Topic:
    with _lock:
        topic = Topic(title=payload.title.strip())
        state.topics.append(topic)
        save_state(state)
    return topic


@app.post("/api/topics/bulk", response_model=List[Topic])
def create_topics_bulk(payload: BulkCreate) -> List[Topic]:
    """Split a pasted block of text into one topic card per line.

    Skips titles that already exist (case-insensitive) so re-pasting a list
    doesn't create duplicates. Returns only the newly created cards.
    """
    with _lock:
        existing = {t.title.strip().lower() for t in state.topics}
        created: List[Topic] = []
        for path, title, notes in parse_topics(payload.text):
            key = title.lower()
            if key in existing:
                continue
            existing.add(key)
            topic = Topic(title=title, notes=notes, path=path)
            state.topics.append(topic)
            created.append(topic)
        if created:
            save_state(state)
    return created


@app.delete("/api/topics")
def delete_all_topics() -> dict:
    with _lock:
        count = len(state.topics)
        state.topics = []
        save_state(state)
    return {"ok": True, "deleted": count}


@app.put("/api/topics/{topic_id}", response_model=Topic)
def update_topic(topic_id: str, payload: TopicUpdate) -> Topic:
    with _lock:
        for topic in state.topics:
            if topic.id == topic_id:
                data = payload.model_dump(exclude_none=True)
                for key, value in data.items():
                    setattr(topic, key, value)
                save_state(state)
                return topic
    raise HTTPException(status_code=404, detail="Topic not found")


@app.delete("/api/topics/{topic_id}")
def delete_topic(topic_id: str) -> dict:
    with _lock:
        before = len(state.topics)
        state.topics = [t for t in state.topics if t.id != topic_id]
        if len(state.topics) == before:
            raise HTTPException(status_code=404, detail="Topic not found")
        save_state(state)
    return {"ok": True}


# --- Plan generation (Grok) -------------------------------------------------
class RefineRequest(BaseModel):
    prompt: str


class PlanEdit(BaseModel):
    plan: str


def _find(topic_id: str) -> Optional[Topic]:
    return next((t for t in state.topics if t.id == topic_id), None)


def _find_by_slug(slug: str) -> Optional[Topic]:
    return next((t for t in state.topics if t.slug == slug), None)


def _work_dir(topic: Topic) -> Path:
    """The concept's real working directory — where its code and git history
    live — with history seeded from the source repo if it has none yet.

    Full-stack concepts run from ``fullstack/<slug>``; everything else from the
    static ``workspace/<slug>``. Either way we adopt the source repo's real
    history (the copies were made without it) so review/revert operate on the
    genuine timeline rather than a phantom "Initial commit".
    """
    if topic.fullstack:
        d = launcher.RUNTIME / topic.slug
        if not d.exists() and topic.slug in launcher.SPECS:
            d = launcher._prepare(topic.slug)
    else:
        d = agent.topic_dir(topic.slug)
    agent.seed_history(d, launcher.SRC / topic.slug)
    return d


def _ensure_slug(topic: Topic) -> str:
    """Assign a unique kebab-case slug + subfolder if the topic lacks one."""
    if not topic.slug:
        taken = {t.slug for t in state.topics if t.slug}
        topic.slug = agent.slugify(topic.title or "topic", taken)
    agent.topic_dir(topic.slug)  # create the folder — first thing, per spec
    return topic.slug


def _set(topic_id: str, **fields) -> None:
    with _lock:
        topic = _find(topic_id)
        if not topic:
            return
        for key, value in fields.items():
            setattr(topic, key, value)
        save_state(state)


def _plan_job(topic_id: str, feedback: Optional[str] = None) -> None:
    with _lock:
        topic = _find(topic_id)
        if not topic:
            return
        topic.planStatus = "planning"
        topic.planError = ""
        slug = _ensure_slug(topic)
        title, notes, blurb, meta = topic.title, topic.notes, topic.blurb, state.metaPrompt
        session_id = topic.sessionId or None
        existing_plan = topic.plan
        save_state(state)

    _log_reset(topic_id)
    recorder, emit = _start_run(
        "refine" if feedback is not None else "plan", topic_id, slug, title
    )
    cwd = agent.topic_dir(slug)
    if feedback is not None:
        # Sync any manual edits to disk so the agent refines the latest text.
        if existing_plan:
            (cwd / agent.PLAN_FILE).write_text(existing_plan)
        emit(f"Refining plan: {feedback}")
        prompt = agent.refine_prompt(feedback)
    else:
        emit(f"Drafting a learning plan for “{title}”…")
        context = "\n".join(p for p in (blurb, notes) if p)
        prompt = agent.build_plan_prompt(title, context, meta)

    result = agent.run_agent(
        prompt, cwd, on_line=emit, session_id=session_id, recorder=recorder
    )
    plan_path = cwd / agent.PLAN_FILE
    plan_text = plan_path.read_text() if plan_path.exists() else ""

    if result["error"] or not plan_text.strip():
        error = result["error"] or "Agent produced no PLAN.md"
        recorder.finish("error", error=error, exit_code=result.get("exitCode"))
        _set(
            topic_id,
            planStatus="error",
            planError=error,
            sessionId=result["sessionId"] or "",
        )
    else:
        recorder.finish("success", exit_code=result.get("exitCode"))
        _set(
            topic_id,
            planStatus="ready",
            plan=plan_text,
            sessionId=result["sessionId"] or "",
            planError="",
        )


def _consolidate_job(new_id: str, src_plans: list, src_ids: List[str], meta: str) -> None:
    """Synthesize several ready plans into one; on success, retire the sources.

    ``src_plans`` is a list of (title, plan_text) captured at request time so
    the merge is unaffected by later edits, and the originals stay intact until
    the new plan lands (a failed run leaves the board untouched).
    """
    with _lock:
        topic = _find(new_id)
        if not topic:
            return
        topic.planStatus = "planning"
        topic.planError = ""
        slug = _ensure_slug(topic)
        save_state(state)

    _log_reset(new_id)
    with _lock:
        t = _find(new_id)
        run_title = t.title if t else ""
    recorder, emit = _start_run("consolidate", new_id, slug, run_title)
    cwd = agent.topic_dir(slug)
    emit(f"Consolidating {len(src_plans)} plans into one unified plan…")
    result = agent.run_agent(
        agent.consolidate_prompt(src_plans, meta), cwd, on_line=emit, recorder=recorder
    )
    plan_path = cwd / agent.PLAN_FILE
    plan_text = plan_path.read_text() if plan_path.exists() else ""

    if result["error"] or not plan_text.strip():
        error = result["error"] or "Agent produced no PLAN.md"
        recorder.finish("error", error=error, exit_code=result.get("exitCode"))
        _set(
            new_id,
            planStatus="error",
            planError=error,
            sessionId=result["sessionId"] or "",
        )
        return

    recorder.finish("success", exit_code=result.get("exitCode"))
    title = agent.plan_title(plan_text)
    with _lock:
        topic = _find(new_id)
        if not topic:
            return
        topic.planStatus = "ready"
        topic.plan = plan_text
        topic.sessionId = result["sessionId"] or ""
        topic.planError = ""
        if title:
            topic.title = title
        # Retire the sources now that the merged plan is safely in hand.
        state.topics = [t for t in state.topics if t.id == new_id or t.id not in src_ids]
        save_state(state)


def _build_job(topic_id: str, build_budget_usd: object = agent._BUDGET_UNSET) -> None:
    with _lock:
        topic = _find(topic_id)
        if not topic:
            return
        topic.planStatus = "building"
        topic.planError = ""
        slug = _ensure_slug(topic)
        plan_text = topic.plan
        title = topic.title
        save_state(state)

    _log_reset(topic_id)
    recorder, emit = _start_run("build", topic_id, slug, title)
    cwd = agent.topic_dir(slug)
    if plan_text:
        (cwd / agent.PLAN_FILE).write_text(plan_text)
    emit("Copying the concept template…")
    agent.copy_template(cwd)
    emit("Building the app from the approved plan…")
    result = agent.run_agent(
        agent.build_prompt(),
        cwd,
        on_line=emit,
        dangerously_skip=True,
        timeout=agent.BUILD_TIMEOUT,
        recorder=recorder,
        apply_build_budget=True,
        build_budget_usd=build_budget_usd,
    )
    if result["error"]:
        recorder.finish("error", error=result["error"], exit_code=result.get("exitCode"))
        _set(topic_id, planStatus="error", planError=result["error"])
        return

    # Re-build with the right base path so we can serve it under /concepts/<slug>/.
    emit("Preparing the concept for viewing…")
    build_ok = agent.finalize_build(cwd, f"/concepts/{slug}/", emit)
    _run_verification_gates(recorder, cwd, emit, build_ok)
    if build_ok:
        emit("Committing initial build to git…")
        agent.git_commit(cwd, f"Build: {title}")
        recorder.finish("success", exit_code=result.get("exitCode"))
        _set(topic_id, planStatus="built", planError="")
    else:
        error = "Build succeeded but the servable bundle failed to compile."
        recorder.finish("error", error=error, exit_code=result.get("exitCode"))
        _set(topic_id, planStatus="error", planError=error)


def _improve_job(topic_id: str, request: str) -> None:
    with _lock:
        topic = _find(topic_id)
        if not topic:
            return
        topic.planStatus = "building"
        topic.planError = ""
        _ensure_slug(topic)
        session_id = topic.sessionId or None
        slug = topic.slug
        fullstack = topic.fullstack
        save_state(state)

    _log_reset(topic_id)
    recorder, emit = _start_run("improve", topic_id, slug, topic.title)
    cwd = _work_dir(topic)
    emit(f"Requesting improvement: {request}")
    result = agent.run_agent(
        agent.improve_prompt(request),
        cwd,
        on_line=emit,
        session_id=session_id,
        dangerously_skip=True,
        timeout=agent.BUILD_TIMEOUT,
        recorder=recorder,
    )
    if result["error"]:
        # The agent's own `npm run build` (default base '/') may have already
        # overwritten the served dist during its verification. Re-finalize with
        # the correct base so a failed improve never leaves a 404-ing bundle.
        if not fullstack:
            agent.finalize_build(cwd, f"/concepts/{slug}/", emit)
        recorder.finish("error", error=result["error"], exit_code=result.get("exitCode"))
        _set(topic_id, planStatus="error", planError=result["error"],
             sessionId=result["sessionId"] or "")
        return

    # Full-stack apps are launched, not statically served, so there is no bundle
    # to compile — just commit the change (it takes effect on the next launch).
    if fullstack:
        emit("Committing changes to git…")
        agent.git_commit(cwd, f"Improve: {request}")
        recorder.set_gate("lint", agent.run_lint_gate(cwd, emit))
        recorder.set_gate("validator", agent.run_validator_gate(cwd, emit))
        recorder.finish("success", exit_code=result.get("exitCode"))
        _set(topic_id, planStatus="built", planError="", sessionId=result["sessionId"] or "")
        emit("✓ Saved. Relaunch the concept to see the changes.")
        return

    emit("Rebuilding the servable bundle…")
    build_ok = agent.finalize_build(cwd, f"/concepts/{slug}/", emit)
    _run_verification_gates(recorder, cwd, emit, build_ok)
    if build_ok:
        emit("Committing changes to git…")
        agent.git_commit(cwd, f"Improve: {request}")
        recorder.finish("success", exit_code=result.get("exitCode"))
        _set(topic_id, planStatus="built", planError="", sessionId=result["sessionId"] or "")
    else:
        error = "Improvement broke the build; nothing was committed."
        recorder.finish("error", error=error, exit_code=result.get("exitCode"))
        _set(topic_id, planStatus="error", planError=error)


def _revert_job(topic_id: str, commit_hash: str) -> None:
    with _lock:
        topic = _find(topic_id)
        if not topic:
            return
        topic.planStatus = "building"
        topic.planError = ""
        _ensure_slug(topic)
        slug = topic.slug
        fullstack = topic.fullstack
        save_state(state)

    _log_reset(topic_id)
    emit = lambda line: _log_append(topic_id, line)
    cwd = _work_dir(topic)
    # Snapshot the current state first so the revert itself is reversible and no
    # uncommitted work is lost by the hard reset inside git_revert_to.
    agent.git_commit(cwd, "Snapshot before revert")
    emit(f"Reverting to commit {commit_hash[:8]}…")
    agent.git_revert_to(cwd, commit_hash)

    if fullstack:
        _set(topic_id, planStatus="built", planError="")
        emit("✓ Reverted. Relaunch the concept to see this version.")
        return

    # The target's servable bundle was restored straight from git — just serve it.
    # No Grok, no npm rebuild; switching a version is a pure git restore.
    if agent.has_committed_dist(cwd, commit_hash):
        _set(topic_id, planStatus="built", planError="")
        emit("✓ Now serving this version.")
        return

    # Older version saved before bundles were versioned — rebuild it once.
    emit("Rebuilding the servable bundle…")
    if agent.finalize_build(cwd, f"/concepts/{slug}/", emit):
        _set(topic_id, planStatus="built", planError="")
    else:
        _set(topic_id, planStatus="error",
             planError="Reverted, but that version failed to build.")


@app.post("/api/plans/generate")
def generate_plans() -> dict:
    """Queue plan generation for every topic that doesn't have one yet."""
    with _lock:
        todo = [t for t in state.topics if t.planStatus in ("none", "error")]
        for topic in todo:
            topic.planStatus = "queued"
            topic.planError = ""
            _ensure_slug(topic)
        save_state(state)
        ids = [t.id for t in todo]
    for topic_id in ids:
        agent.EXECUTOR.submit(_plan_job, topic_id)
    return {"queued": len(ids), "concurrency": agent.CONCURRENCY}


def _common_path_prefix(paths: List[List[str]]) -> List[str]:
    """Longest shared leading path so the merged card lands in the common group."""
    if not paths:
        return []
    prefix = list(paths[0])
    for path in paths[1:]:
        i = 0
        while i < len(prefix) and i < len(path) and prefix[i] == path[i]:
            i += 1
        prefix = prefix[:i]
    return prefix


@app.post("/api/topics/consolidate", response_model=Topic)
def consolidate_topics(payload: ConsolidateRequest) -> Topic:
    """Merge several plan-ready topics into one synthesized plan.

    Only applies to topics still in plan mode (status ``ready`` with a plan).
    Creates a new topic whose plan is generated by the agent; the sources are
    removed once the merge succeeds (handled in the background job).
    """
    with _lock:
        sources = [t for t in (_find(i) for i in payload.ids) if t]
        if len(sources) < 2:
            raise HTTPException(status_code=400, detail="Select at least two plans to consolidate")
        for t in sources:
            if t.planStatus != "ready" or not t.plan.strip():
                raise HTTPException(
                    status_code=400,
                    detail="Every selected topic must have a ready plan (still in plan mode)",
                )
        path = _common_path_prefix([t.path for t in sources])
        joined = " | ".join(t.title for t in sources)
        new = Topic(
            title=f"Merging Topics: {joined}"[:120],
            planStatus="queued",
            path=path,
        )
        state.topics.append(new)
        _ensure_slug(new)
        src_plans = [(t.title, t.plan) for t in sources]
        src_ids = [t.id for t in sources]
        meta = state.metaPrompt
        save_state(state)
    agent.EXECUTOR.submit(_consolidate_job, new.id, src_plans, src_ids, meta)
    return new


@app.post("/api/topics/{topic_id}/plan", response_model=Topic)
def generate_one_plan(topic_id: str) -> Topic:
    """(Re)generate a single plan from scratch."""
    with _lock:
        topic = _find(topic_id)
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")
        topic.planStatus = "queued"
        topic.planError = ""
        topic.sessionId = ""  # fresh session for a from-scratch regenerate
        _ensure_slug(topic)
        save_state(state)
    agent.EXECUTOR.submit(_plan_job, topic_id)
    return topic


@app.post("/api/topics/{topic_id}/plan/refine", response_model=Topic)
def refine_plan(topic_id: str, payload: RefineRequest) -> Topic:
    with _lock:
        topic = _find(topic_id)
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")
        if not topic.plan:
            raise HTTPException(status_code=400, detail="No plan to refine yet")
        topic.planStatus = "queued"
        topic.planError = ""
        save_state(state)
    agent.EXECUTOR.submit(_plan_job, topic_id, payload.prompt)
    return topic


@app.put("/api/topics/{topic_id}/plan", response_model=Topic)
def edit_plan(topic_id: str, payload: PlanEdit) -> Topic:
    """Save a human's manual edits to the plan (also written to disk)."""
    with _lock:
        topic = _find(topic_id)
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")
        topic.plan = payload.plan
        if topic.planStatus in ("none", "error"):
            topic.planStatus = "ready"
        slug = _ensure_slug(topic)
        save_state(state)
    (agent.topic_dir(slug) / agent.PLAN_FILE).write_text(payload.plan)
    return topic


class BuildRequest(BaseModel):
    """Optional per-build dollar budget (Grok Build only).

    * Field omitted → use global ``grok.maxBuildBudgetUsd`` from settings.
    * ``null`` / empty → unlimited for this build.
    * Positive number → hard cap (converted to goal tokens server-side).
    """
    budgetUsd: Optional[float] = None


@app.post("/api/topics/{topic_id}/build", response_model=Topic)
async def build_topic(topic_id: str, request: Request) -> Topic:
    # Parse body loosely so older clients that POST with an empty body still work.
    build_budget_usd: object = agent._BUDGET_UNSET
    try:
        raw = await request.body()
        if raw and raw.strip() and raw.strip() not in (b"null", b"undefined"):
            data = json.loads(raw)
            if isinstance(data, dict) and "budgetUsd" in data:
                build_budget_usd = data.get("budgetUsd")
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        pass

    with _lock:
        topic = _find(topic_id)
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")
        if not topic.plan:
            raise HTTPException(status_code=400, detail="Approve a plan first")
        topic.planStatus = "building"
        topic.planError = ""
        save_state(state)
    agent.EXECUTOR.submit(_build_job, topic_id, build_budget_usd)
    return topic


class HashRequest(BaseModel):
    hash: str


@app.post("/api/topics/{topic_id}/improve", response_model=Topic)
def improve_topic(topic_id: str, payload: RefineRequest) -> Topic:
    with _lock:
        topic = _find(topic_id)
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")
        if topic.planStatus != "built":
            raise HTTPException(status_code=400, detail="Build the concept first")
        topic.planStatus = "building"
        topic.planError = ""
        save_state(state)
    agent.EXECUTOR.submit(_improve_job, topic_id, payload.prompt)
    return topic


@app.get("/api/topics/{topic_id}/history")
def topic_history(topic_id: str) -> dict:
    with _lock:
        topic = _find(topic_id)
        if not topic or not topic.slug:
            raise HTTPException(status_code=404, detail="Topic not found")
    cwd = _work_dir(topic)
    return {"commits": agent.git_log(cwd), "served": agent.served_hash(cwd)}


@app.post("/api/topics/{topic_id}/revert", response_model=Topic)
def revert_topic(topic_id: str, payload: HashRequest) -> Topic:
    with _lock:
        topic = _find(topic_id)
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")
        if topic.planStatus != "built":
            raise HTTPException(status_code=400, detail="Nothing built to revert")
        topic.planStatus = "building"
        topic.planError = ""
        save_state(state)
    agent.EXECUTOR.submit(_revert_job, topic_id, payload.hash)
    return topic


@app.get("/api/topics/{topic_id}/log")
def get_log(topic_id: str) -> dict:
    """Live progress lines streamed from the topic's Grok run."""
    with _lock:
        topic = _find(topic_id)
        status = topic.planStatus if topic else "none"
    return {"status": status, "lines": _log_get(topic_id)}


# --- Run instrumentation (persisted per-run logs + metrics) ------------------
@app.get("/api/runs/metrics")
def run_metrics() -> dict:
    """Aggregates for the metrics dashboard (KPIs, gate outcomes, per-model)."""
    return runs.metrics_summary()


@app.get("/api/runs")
def list_runs(topicId: Optional[str] = None, kind: Optional[str] = None,
              limit: int = 200) -> dict:
    """Structured per-run records, newest first."""
    return {"runs": runs.list_runs(topic_id=topicId, kind=kind, limit=limit)}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    rec = runs.get_run(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Run not found")
    return rec


@app.get("/api/runs/{run_id}/events")
def get_run_events(run_id: str, offset: int = 0, limit: int = 500) -> dict:
    """Raw stream events (the persisted session context), paginated."""
    if not runs.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return runs.run_events(run_id, offset=offset, limit=limit)


@app.get("/api/runs/{run_id}/log")
def get_run_log(run_id: str) -> dict:
    """The persisted human-readable log for this run."""
    if not runs.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return {"lines": runs.run_log_text(run_id).splitlines()}


@app.get("/api/runs/{run_id}/export")
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


# --- Full-stack concept apps (launched on demand) ---------------------------
@app.post("/api/concepts/{slug}/launch")
def launch_concept(slug: str) -> dict:
    return launcher.launch(slug)


@app.post("/api/concepts/{slug}/stop")
def stop_concept(slug: str) -> dict:
    return launcher.stop(slug)


@app.get("/api/concepts/{slug}/app")
def concept_app_status(slug: str) -> dict:
    return launcher.status(slug)


# --- Slug-scoped tools (used by the in-page concept widget) ------------------
# These mirror the topic-id endpoints but resolve by slug, so the widget baked
# into a served concept page can drive improve / history / revert / status
# knowing only its own URL.
@app.get("/api/concepts/{slug}/status")
def concept_status(slug: str) -> dict:
    topic = _find_by_slug(slug)
    if not topic:
        raise HTTPException(status_code=404, detail="Concept not found")
    return {"status": topic.planStatus, "error": topic.planError}


@app.get("/api/concepts/{slug}/log")
def concept_log(slug: str) -> dict:
    """Live Grok output for the in-page widget's rebuild view."""
    topic = _find_by_slug(slug)
    if not topic:
        raise HTTPException(status_code=404, detail="Concept not found")
    return {
        "status": topic.planStatus,
        "error": topic.planError,
        "lines": _log_get(topic.id),
    }


@app.get("/api/concepts/{slug}/history")
def concept_history(slug: str) -> dict:
    with _lock:
        topic = _find_by_slug(slug)
        if not topic:
            raise HTTPException(status_code=404, detail="Concept not found")
        status = topic.planStatus
    cwd = _work_dir(topic)
    return {"commits": agent.git_log(cwd), "served": agent.served_hash(cwd), "status": status}


@app.post("/api/concepts/{slug}/improve")
def concept_improve(slug: str, payload: RefineRequest) -> dict:
    with _lock:
        topic = _find_by_slug(slug)
        if not topic:
            raise HTTPException(status_code=404, detail="Concept not found")
        if topic.planStatus != "built":
            raise HTTPException(status_code=400, detail="Build the concept first")
        topic.planStatus = "building"
        topic.planError = ""
        topic_id = topic.id
        save_state(state)
    agent.EXECUTOR.submit(_improve_job, topic_id, payload.prompt)
    return {"status": "building"}


@app.post("/api/concepts/{slug}/revert")
def concept_revert(slug: str, payload: HashRequest) -> dict:
    with _lock:
        topic = _find_by_slug(slug)
        if not topic:
            raise HTTPException(status_code=404, detail="Concept not found")
        if topic.planStatus != "built":
            raise HTTPException(status_code=400, detail="Nothing built to revert")
        topic.planStatus = "building"
        topic.planError = ""
        topic_id = topic.id
        save_state(state)
    agent.EXECUTOR.submit(_revert_job, topic_id, payload.hash)
    return {"status": "building"}


# --- Live tutor chat (read-only Q&A about this concept) ----------------------
class ChatRequest(BaseModel):
    message: str


@app.get("/api/concepts/{slug}/chat")
def concept_chat_history(slug: str) -> dict:
    topic = _find_by_slug(slug)
    if not topic:
        raise HTTPException(status_code=404, detail="Concept not found")
    with _CHAT_LOCK:
        messages = list(_CHAT.get(slug, []))
    return {"messages": messages, "title": topic.title}


@app.delete("/api/concepts/{slug}/chat")
def concept_chat_clear(slug: str) -> dict:
    topic = _find_by_slug(slug)
    if not topic:
        raise HTTPException(status_code=404, detail="Concept not found")
    with _CHAT_LOCK:
        _CHAT.pop(slug, None)
    return {"ok": True}


@app.post("/api/concepts/{slug}/chat")
def concept_chat(slug: str, payload: ChatRequest):
    """Stream a tutor reply (SSE). Does not mutate the app — Q&A only."""
    topic = _find_by_slug(slug)
    if not topic:
        raise HTTPException(status_code=404, detail="Concept not found")
    text = (payload.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty message")

    with _CHAT_LOCK:
        history = list(_CHAT.get(slug, []))
        history.append({"role": "user", "content": text})
        # Cap history so context stays lean across long chats.
        if len(history) > _CHAT_CAP:
            history = history[-_CHAT_CAP:]
        _CHAT[slug] = history

    context = agent.topic_context(slug, topic.title, topic.blurb)
    system = agent.chat_system_prompt(context)
    api_messages = [{"role": "system", "content": system}, *history]

    def event_stream():
        # Thread-safe queue of text deltas from the xAI stream worker.
        import queue as _queue

        q: _queue.Queue = _queue.Queue()
        done = threading.Event()
        result_box: dict = {}

        def on_delta(chunk: str) -> None:
            q.put(chunk)

        def worker() -> None:
            try:
                result_box["r"] = agent.stream_chat(api_messages, on_delta=on_delta)
            except Exception as e:  # noqa: BLE001
                result_box["r"] = {"text": "", "error": str(e), "usage": None}
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()
        yield f"data: {json.dumps({'type': 'start'})}\n\n"
        # Drain as tokens arrive.
        while not done.is_set() or not q.empty():
            try:
                chunk = q.get(timeout=0.05)
                yield f"data: {json.dumps({'type': 'text', 'data': chunk})}\n\n"
            except _queue.Empty:
                continue
        r = result_box.get("r") or {"text": "", "error": "no result", "usage": None}
        reply = (r.get("text") or "").strip()
        if r.get("error") and not reply:
            yield f"data: {json.dumps({'type': 'error', 'message': r['error']})}\n\n"
        else:
            if reply:
                with _CHAT_LOCK:
                    hist = list(_CHAT.get(slug, []))
                    hist.append({"role": "assistant", "content": reply})
                    if len(hist) > _CHAT_CAP:
                        hist = hist[-_CHAT_CAP:]
                    _CHAT[slug] = hist
            if r.get("error"):
                yield f"data: {json.dumps({'type': 'error', 'message': r['error']})}\n\n"
            yield f"data: {json.dumps({'type': 'end', 'text': reply})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# --- Credits (console.x.ai prepaid balance) ---------------------------------
class BudgetUpdate(BaseModel):
    budgetUsd: Optional[float] = None  # ignored; kept for API compat


@app.get("/api/credits")
def get_credits(force: bool = False) -> dict:
    """Live prepaid $ remaining from console.x.ai (Management API)."""
    return agent.get_balance(force=force)


@app.put("/api/credits/budget")
def set_credit_budget(payload: BudgetUpdate) -> dict:
    """No-op: remaining balance is owned by console.x.ai, not a local budget."""
    return agent.set_budget_usd(payload.budgetUsd)


# --- Serving built concepts -------------------------------------------------
def _widget_js() -> str:
    # Read fresh each request so widget edits show up under --reload.
    return (Path(__file__).parent / "concept_widget.js").read_text()


# Served under /concepts/ so the frontend dev-server proxy (which forwards
# /concepts but not arbitrary top-level paths) reaches it in dev too. This
# route is declared before the catch-all serve_concept, so it wins.
@app.get("/concepts/__widget.js")
def concept_widget_js() -> Response:
    return Response(
        content=_widget_js(),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


def _inject_widget(html: str, slug: str) -> str:
    """Bake the tools widget into a concept's index.html before serving it."""
    tag = (
        f'<script>window.__CONCEPT_SLUG__={json.dumps(slug)};</script>'
        '<script src="/concepts/__widget.js" defer></script>'
    )
    lower = html.lower()
    idx = lower.rfind("</body>")
    if idx == -1:
        return html + tag
    return html[:idx] + tag + html[idx:]


@app.get("/concepts/{slug}/{path:path}")
def serve_concept(slug: str, path: str = ""):
    """Serve a built concept's static bundle, with SPA fallback to index.html."""
    root = (agent.WORKSPACE / slug / "dist").resolve()
    if not root.exists():
        raise HTTPException(status_code=404, detail="Concept not built")
    # Concept HTML must not be cached, or a browser can serve a stale copy that
    # predates the injected tools widget.
    no_cache = {"Cache-Control": "no-cache"}
    if path:
        target = (root / path).resolve()
        # Guard against path traversal outside the dist folder.
        if str(target).startswith(str(root)) and target.is_file():
            if target.suffix.lower() in (".html", ".htm"):
                return HTMLResponse(_inject_widget(target.read_text(), slug), headers=no_cache)
            return FileResponse(target)
    index = root / "index.html"
    if index.is_file():
        return HTMLResponse(_inject_widget(index.read_text(), slug), headers=no_cache)
    raise HTTPException(status_code=404, detail="Concept not built")
