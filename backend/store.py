"""Topic/state persistence: pydantic models, data.json load/save, lookups."""


from __future__ import annotations


import json


import re


import threading


import uuid


from pathlib import Path


from typing import List, Optional


from pydantic import BaseModel, Field


import agent


import launcher


DATA_FILE = Path(__file__).parent / "data.json"


_lock = threading.Lock()


# Plan lifecycle: none -> queued -> planning -> ready -> building -> built
# (any step can land on "error"). Transient states are reset on startup.
_TRANSIENT = {"queued", "planning", "building"}


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


# --- Agent driver settings (Grok Build only) --------------------------------
class DriverSettingsUpdate(BaseModel):
    """Partial or full settings blob from the dashboard modal."""
    driver: Optional[str] = None  # ignored; always coerced to grok
    grok: Optional[dict] = None


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


class BuildRequest(BaseModel):
    """Optional per-build dollar budget (Grok Build only).

    * Field omitted → use global ``grok.maxBuildBudgetUsd`` from settings.
    * ``null`` / empty → unlimited for this build.
    * Positive number → hard cap (converted to goal tokens server-side).
    """
    budgetUsd: Optional[float] = None


class HashRequest(BaseModel):
    hash: str


# --- Live tutor chat (read-only Q&A about this concept) ----------------------
class ChatRequest(BaseModel):
    message: str


# --- Credits (console.x.ai prepaid balance) ---------------------------------
class BudgetUpdate(BaseModel):
    budgetUsd: Optional[float] = None  # ignored; kept for API compat
