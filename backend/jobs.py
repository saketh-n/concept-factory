"""Background agent jobs: plan/build/improve/revert/consolidate runners
plus the in-memory live log ring and run-record helpers."""


from __future__ import annotations


import threading


from pathlib import Path


from typing import List, Optional



import agent


import runs


from store import _ensure_slug, _find, _lock, _set, _work_dir, save_state, state


# Live progress streamed from each Grok run, kept in memory only (not
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
