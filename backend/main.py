"""Concept Factory backend.

A tiny FastAPI service that persists a meta prompt and a list of topic cards
to a JSON file on disk. State is loaded on startup and written back on every
mutation, so everything survives a server restart.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

import agent
import launcher

DATA_FILE = Path(__file__).parent / "data.json"
_lock = threading.Lock()

# Plan lifecycle: none -> queued -> planning -> ready -> building -> built
# (any step can land on "error"). Transient states are reset on startup.
_TRANSIENT = {"queued", "planning", "building"}

# Live progress streamed from each Claude Code run, kept in memory only (not
# persisted — it's ephemeral job output). topic_id -> list[str] of log lines.
_LOGS: dict = {}
_LOGS_LOCK = threading.Lock()
_LOG_CAP = 500


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


@app.get("/api/state", response_model=State)
def get_state() -> State:
    return state


@app.put("/api/meta-prompt", response_model=State)
def update_meta_prompt(payload: MetaPromptUpdate) -> State:
    with _lock:
        state.metaPrompt = payload.metaPrompt
        save_state(state)
    return state


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


# --- Plan generation (Claude Code) ------------------------------------------
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
    emit = lambda line: _log_append(topic_id, line)
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

    result = agent.run_claude(prompt, cwd, on_line=emit, session_id=session_id)
    plan_path = cwd / agent.PLAN_FILE
    plan_text = plan_path.read_text() if plan_path.exists() else ""

    if result["error"] or not plan_text.strip():
        _set(
            topic_id,
            planStatus="error",
            planError=result["error"] or "Agent produced no PLAN.md",
            sessionId=result["sessionId"] or "",
        )
    else:
        _set(
            topic_id,
            planStatus="ready",
            plan=plan_text,
            sessionId=result["sessionId"] or "",
            planError="",
        )


def _build_job(topic_id: str) -> None:
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
    emit = lambda line: _log_append(topic_id, line)
    cwd = agent.topic_dir(slug)
    if plan_text:
        (cwd / agent.PLAN_FILE).write_text(plan_text)
    emit("Copying the concept template…")
    agent.copy_template(cwd)
    emit("Building the app from the approved plan…")
    result = agent.run_claude(
        agent.build_prompt(),
        cwd,
        on_line=emit,
        dangerously_skip=True,
        timeout=agent.BUILD_TIMEOUT,
    )
    if result["error"]:
        _set(topic_id, planStatus="error", planError=result["error"])
        return

    # Re-build with the right base path so we can serve it under /concepts/<slug>/.
    emit("Preparing the concept for viewing…")
    if agent.finalize_build(cwd, f"/concepts/{slug}/", emit):
        emit("Committing initial build to git…")
        agent.git_commit(cwd, f"Build: {title}")
        _set(topic_id, planStatus="built", planError="")
    else:
        _set(
            topic_id,
            planStatus="error",
            planError="Build succeeded but the servable bundle failed to compile.",
        )


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
    emit = lambda line: _log_append(topic_id, line)
    cwd = _work_dir(topic)
    # Guarantee a restorable baseline BEFORE Claude Code touches anything. This
    # appends to the concept's real history (never replaces it), so a bad change
    # can always be rolled back.
    agent.git_commit(cwd, "Snapshot before improvement")
    if not (cwd / ".git").exists():
        _set(topic_id, planStatus="error",
             planError="Could not create a git snapshot to protect your work; nothing was changed.")
        return
    emit(f"Requesting improvement: {request}")
    result = agent.run_claude(
        agent.improve_prompt(request),
        cwd,
        on_line=emit,
        session_id=session_id,
        dangerously_skip=True,
        timeout=agent.BUILD_TIMEOUT,
    )
    if result["error"]:
        _set(topic_id, planStatus="error", planError=result["error"],
             sessionId=result["sessionId"] or "")
        return

    # Full-stack apps are launched, not statically served, so there is no bundle
    # to compile — just commit the change (it takes effect on the next launch).
    if fullstack:
        emit("Committing changes to git…")
        agent.git_commit(cwd, f"Improve: {request}")
        _set(topic_id, planStatus="built", planError="", sessionId=result["sessionId"] or "")
        emit("✓ Saved. Relaunch the concept to see the changes.")
        return

    emit("Rebuilding the servable bundle…")
    if agent.finalize_build(cwd, f"/concepts/{slug}/", emit):
        emit("Committing changes to git…")
        agent.git_commit(cwd, f"Improve: {request}")
        _set(topic_id, planStatus="built", planError="", sessionId=result["sessionId"] or "")
    else:
        _set(topic_id, planStatus="error",
             planError="Improvement broke the build; nothing was committed.")


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


@app.post("/api/topics/{topic_id}/build", response_model=Topic)
def build_topic(topic_id: str) -> Topic:
    with _lock:
        topic = _find(topic_id)
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")
        if not topic.plan:
            raise HTTPException(status_code=400, detail="Approve a plan first")
        topic.planStatus = "building"
        topic.planError = ""
        save_state(state)
    agent.EXECUTOR.submit(_build_job, topic_id)
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
    return {"commits": agent.git_log(_work_dir(topic))}


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
    """Live progress lines streamed from the topic's Claude Code run."""
    with _lock:
        topic = _find(topic_id)
        status = topic.planStatus if topic else "none"
    return {"status": status, "lines": _log_get(topic_id)}


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
    """Live Claude Code output for the in-page widget's rebuild view."""
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
    return {"commits": agent.git_log(_work_dir(topic)), "status": status}


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


# --- Serving built concepts -------------------------------------------------
_WIDGET_JS = (Path(__file__).parent / "concept_widget.js").read_text()


# Served under /concepts/ so the frontend dev-server proxy (which forwards
# /concepts but not arbitrary top-level paths) reaches it in dev too. This
# route is declared before the catch-all serve_concept, so it wins.
@app.get("/concepts/__widget.js")
def concept_widget_js() -> Response:
    return Response(
        content=_WIDGET_JS,
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
