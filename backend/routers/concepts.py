"""Concept serving + widget, slug-scoped tools, tutor chat, full-stack apps."""


from __future__ import annotations


import json


import threading


from pathlib import Path


from fastapi import APIRouter, HTTPException


from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse


import agent


import launcher


from store import (
    ChatRequest,
    HashRequest,
    RefineRequest,
    _find_by_slug,
    _lock,
    _work_dir,
    save_state,
    state,
)


from jobs import _improve_job, _log_get, _revert_job


router = APIRouter()


# Per-concept tutor chat history (slug -> [{role, content}, ...]). Ephemeral —
# cleared on server restart. System prompt is rebuilt each turn, not stored.
_CHAT: dict = {}


_CHAT_LOCK = threading.Lock()


_CHAT_CAP = 40  # max user+assistant turns kept (system is separate)


# --- Full-stack concept apps (launched on demand) ---------------------------
@router.post("/api/concepts/{slug}/launch")
def launch_concept(slug: str) -> dict:
    return launcher.launch(slug)


@router.post("/api/concepts/{slug}/stop")
def stop_concept(slug: str) -> dict:
    return launcher.stop(slug)


@router.get("/api/concepts/{slug}/app")
def concept_app_status(slug: str) -> dict:
    return launcher.status(slug)


# --- Slug-scoped tools (used by the in-page concept widget) ------------------
# These mirror the topic-id endpoints but resolve by slug, so the widget baked
# into a served concept page can drive improve / history / revert / status
# knowing only its own URL.
@router.get("/api/concepts/{slug}/status")
def concept_status(slug: str) -> dict:
    topic = _find_by_slug(slug)
    if not topic:
        raise HTTPException(status_code=404, detail="Concept not found")
    return {"status": topic.planStatus, "error": topic.planError}


@router.get("/api/concepts/{slug}/log")
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


@router.get("/api/concepts/{slug}/history")
def concept_history(slug: str) -> dict:
    with _lock:
        topic = _find_by_slug(slug)
        if not topic:
            raise HTTPException(status_code=404, detail="Concept not found")
        status = topic.planStatus
    cwd = _work_dir(topic)
    return {"commits": agent.git_log(cwd), "served": agent.served_hash(cwd), "status": status}


@router.post("/api/concepts/{slug}/improve")
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


@router.post("/api/concepts/{slug}/revert")
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


@router.get("/api/concepts/{slug}/chat")
def concept_chat_history(slug: str) -> dict:
    topic = _find_by_slug(slug)
    if not topic:
        raise HTTPException(status_code=404, detail="Concept not found")
    with _CHAT_LOCK:
        messages = list(_CHAT.get(slug, []))
    return {"messages": messages, "title": topic.title}


@router.delete("/api/concepts/{slug}/chat")
def concept_chat_clear(slug: str) -> dict:
    topic = _find_by_slug(slug)
    if not topic:
        raise HTTPException(status_code=404, detail="Concept not found")
    with _CHAT_LOCK:
        _CHAT.pop(slug, None)
    return {"ok": True}


@router.post("/api/concepts/{slug}/chat")
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


# --- Serving built concepts -------------------------------------------------
def _widget_js() -> str:
    # Read fresh each request so widget edits show up under --reload.
    return (Path(__file__).parent / "concept_widget.js").read_text()


# Served under /concepts/ so the frontend dev-server proxy (which forwards
# /concepts but not arbitrary top-level paths) reaches it in dev too. This
# route is declared before the catch-all serve_concept, so it wins.
@router.get("/concepts/__widget.js")
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


@router.get("/concepts/{slug}/{path:path}")
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
