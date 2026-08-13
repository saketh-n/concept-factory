"""Grok CLI execution: argv construction, streaming, run_agent."""


from __future__ import annotations


import json


import os


import subprocess


import threading


from concurrent.futures import ThreadPoolExecutor


from pathlib import Path


from typing import Any, Callable, List, Optional


from .settings import (
    DRIVER_GROK,
    GROK_BIN,
    _BUDGET_UNSET,
    format_grok_goal_prompt,
    load_settings,
    normalize_settings,
    parse_budget_usd,
    resolve_build_budget_tokens,
)


# Grok is I/O-bound (mostly waiting on the API) but each run spawns a
# process, so we cap concurrency to protect memory and API rate limits.
# 12-core / 18 GB machine → 8 in flight; the rest queue in the executor.
CONCURRENCY = int(os.environ.get("CF_PLAN_CONCURRENCY", "8"))


EXECUTOR = ThreadPoolExecutor(max_workers=CONCURRENCY)


# Per-run wall-clock ceiling (seconds).
PLAN_TIMEOUT = 420


BUILD_TIMEOUT = 1800


# --- Streaming event → human-readable line ---------------------------------
# Grok's --output-format streaming-json emits NDJSON with types:
#   text / thought / end / error  (plus occasional max_turns_reached, etc.)
# Claude Code --output-format stream-json emits system/assistant/result events.
# Tokens arrive one chunk at a time, so we coalesce them into display lines.
class _StreamCoalescer:
    """Buffer token-level text/thought events into skimmable log lines."""

    def __init__(self, on_line: Callable[[str], None], driver_label: str = "Agent") -> None:
        self._emit = on_line
        self._text = ""
        self._thought = ""
        self._thought_shown = False
        self._driver_label = driver_label

    def push(self, evt: dict) -> None:
        etype = evt.get("type")
        if etype == "text":
            self._flush_thought(partial=True)
            self._text += evt.get("data") or ""
            self._flush_text(force=False)
        elif etype == "thought":
            self._flush_text(force=True)
            self._thought += evt.get("data") or ""
            # Thoughts are extremely granular — surface at most one marker so
            # the log stays readable, then drop the rest of the block.
            if not self._thought_shown and len(self._thought.strip()) >= 24:
                self._emit("💭 thinking…")
                self._thought_shown = True
                self._thought = ""
        elif etype == "error":
            self._flush_all()
            msg = (evt.get("message") or evt.get("data") or "error").strip()
            if msg:
                self._emit(f"⚠ {msg}")
        elif etype == "end":
            self._flush_all()
            if evt.get("stopReason") in ("Error", "Cancelled", "MaxTurns"):
                self._emit("⚠ run ended early")
            else:
                self._emit(f"✓ {self._driver_label} finished this turn")
        elif etype == "max_turns_reached":
            self._flush_all()
            self._emit("⚠ max turns reached")
        elif etype == "assistant":
            # Claude Code stream-json: assistant messages with content blocks.
            self._push_claude_assistant(evt)
        elif etype == "result":
            self._flush_all()
            if evt.get("is_error") or evt.get("subtype") == "error":
                msg = (evt.get("result") or evt.get("error") or "error").strip()
                if msg:
                    self._emit(f"⚠ {msg}")
            else:
                self._emit(f"✓ {self._driver_label} finished this turn")
        elif etype == "system" and evt.get("subtype") == "init":
            model = evt.get("model") or ""
            if model:
                self._emit(f"Using model {model}")

    def _push_claude_assistant(self, evt: dict) -> None:
        msg = evt.get("message") or {}
        content = msg.get("content") or []
        if isinstance(content, str):
            self._flush_thought(partial=True)
            self._text += content
            self._flush_text(force=False)
            return
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                self._flush_thought(partial=True)
                self._text += block.get("text") or ""
                self._flush_text(force=False)
            elif btype == "thinking":
                self._flush_text(force=True)
                thinking = (block.get("thinking") or "").strip()
                if thinking and not self._thought_shown:
                    self._emit("💭 thinking…")
                    self._thought_shown = True
            elif btype == "tool_use":
                self._flush_all()
                name = block.get("name") or "tool"
                self._emit(f"→ {name}")

    def _flush_text(self, force: bool) -> None:
        if not self._text:
            return
        # Emit complete lines as they form; force dumps any remainder.
        while True:
            nl = self._text.find("\n")
            if nl < 0:
                break
            line = self._text[:nl].rstrip()
            self._text = self._text[nl + 1 :]
            if line.strip():
                self._emit(line)
        if force and self._text.strip():
            self._emit(self._text.strip())
            self._text = ""
        elif not force and len(self._text) >= 160:
            # Long paragraph without newlines — emit a soft break so the UI
            # updates live rather than waiting for the whole turn.
            cut = self._text.rfind(" ", 0, 160)
            if cut < 40:
                cut = 160
            self._emit(self._text[:cut].strip())
            self._text = self._text[cut:].lstrip()

    def _flush_thought(self, partial: bool) -> None:
        # Drop residual thought buffer when we switch back to text.
        self._thought = ""
        if not partial:
            self._thought_shown = False

    def _flush_all(self) -> None:
        self._flush_text(force=True)
        self._flush_thought(partial=False)


# --- Command construction (pure, unit-tested) -------------------------------
def build_grok_cmd(
    prompt: str,
    cwd: Path,
    *,
    session_id: Optional[str] = None,
    dangerously_skip: bool = False,
    permission_mode: str = "acceptEdits",
    model: str = "",
    reasoning_effort: str = "",
    bin_path: Optional[str] = None,
    budget_tokens: Optional[int] = None,
) -> List[str]:
    """Build the argv for a headless Grok Build turn.

    When ``budget_tokens`` is a positive int, the prompt is wrapped as a
    ``/goal … --budget <tokens>`` invocation so Grok enforces the cap.
    ``None`` / non-positive → unlimited (plain ``-p`` prompt, no budget flag).
    """
    effective_prompt = prompt
    if budget_tokens is not None and int(budget_tokens) > 0:
        effective_prompt = format_grok_goal_prompt(prompt, int(budget_tokens))
    cmd = [
        bin_path or GROK_BIN,
        "-p",
        effective_prompt,
        "--output-format",
        "streaming-json",
        "--always-approve",
        "--cwd",
        str(cwd),
    ]
    if dangerously_skip or permission_mode in ("bypassPermissions", "auto"):
        cmd += ["--permission-mode", "bypassPermissions"]
    elif permission_mode and permission_mode != "acceptEdits":
        cmd += ["--permission-mode", permission_mode]
    if model and str(model).strip():
        cmd += ["--model", str(model).strip()]
    if reasoning_effort and str(reasoning_effort).strip():
        cmd += ["--reasoning-effort", str(reasoning_effort).strip()]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


def build_driver_cmd(
    driver: str,
    prompt: str,
    cwd: Path,
    *,
    settings: Optional[dict] = None,
    session_id: Optional[str] = None,
    dangerously_skip: bool = False,
    permission_mode: Optional[str] = None,
    budget_tokens: Optional[int] = None,
    build_budget_usd: Any = _BUDGET_UNSET,
) -> List[str]:
    """Build argv for the factory agent (always Grok Build).

    ``driver`` is accepted for call-site compat but ignored — Claude is no
    longer a factory path. ``budget_tokens`` wins when provided; otherwise
    ``build_budget_usd`` may resolve a Grok goal token cap.
    """
    del driver  # always Grok
    cfg = normalize_settings(settings)
    g = cfg["grok"]
    tokens = budget_tokens
    if tokens is None and build_budget_usd is not _BUDGET_UNSET:
        tokens = resolve_build_budget_tokens(override=build_budget_usd, settings=cfg)
    elif tokens is None and build_budget_usd is _BUDGET_UNSET:
        # Explicit None budget_tokens + unset override → no budget (non-build).
        tokens = None
    return build_grok_cmd(
        prompt,
        cwd,
        session_id=session_id,
        dangerously_skip=dangerously_skip,
        permission_mode=permission_mode or g.get("permissionMode") or "acceptEdits",
        model=g.get("model") or "",
        reasoning_effort=g.get("reasoningEffort") or "",
        budget_tokens=tokens,
    )


def _run_cli_once(
    cmd: List[str],
    cwd: Path,
    emit: Callable[[str], None],
    session_id: Optional[str],
    timeout: int,
    driver_label: str,
    stream_kind: str,
    recorder=None,
) -> dict:
    """Run one headless CLI turn and normalize its NDJSON stream into log lines.

    ``recorder`` (a runs.RunRecorder) receives every raw stream event for
    persistence + metric extraction; log lines go through ``emit`` as before.
    """
    emit(
        f"{driver_label} session started…"
        if not session_id
        else f"Resuming {driver_label} session {session_id[:8]}…"
    )
    coalescer = _StreamCoalescer(emit, driver_label=driver_label)

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stderr_chunks: List[str] = []
    stderr_thread = threading.Thread(
        target=lambda: stderr_chunks.extend(proc.stderr or []), daemon=True
    )
    stderr_thread.start()

    timer = threading.Timer(timeout, proc.kill)
    timer.start()

    result_session = session_id
    final_error: Optional[str] = None
    try:
        for raw in proc.stdout or []:
            line = raw.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                # Non-JSON noise (rare) — surface a short snippet.
                if line and not line.startswith("{"):
                    emit(line[:200])
                    if recorder is not None:
                        recorder.event({"type": "raw", "data": line[:2000]})
                continue

            if recorder is not None:
                recorder.event(evt)

            if stream_kind == "claude":
                sid = evt.get("session_id") or evt.get("sessionId")
                if sid:
                    result_session = sid
                if evt.get("type") == "result" and (
                    evt.get("is_error") or evt.get("subtype") not in (None, "success")
                ):
                    final_error = (
                        evt.get("result")
                        or evt.get("error")
                        or evt.get("message")
                        or "error"
                    )
                coalescer.push(evt)
            else:
                # Grok streaming-json
                if evt.get("sessionId"):
                    result_session = evt["sessionId"]
                if evt.get("type") == "error":
                    final_error = evt.get("message") or evt.get("data") or "error"
                if evt.get("type") == "end":
                    stop = evt.get("stopReason") or ""
                    if stop in ("Error", "Cancelled"):
                        final_error = final_error or f"stopped: {stop}"
                coalescer.push(evt)
        proc.wait()
    finally:
        timer.cancel()
        stderr_thread.join(timeout=2)

    if proc.returncode not in (0, None) and not final_error:
        detail = "".join(stderr_chunks).strip()[-500:]
        bin_name = Path(cmd[0]).name if cmd else "agent"
        final_error = detail or f"{bin_name} exited with code {proc.returncode}"

    return {
        "sessionId": result_session,
        "error": final_error,
        "exitCode": proc.returncode,
    }


def _looks_like_session_error(err: Optional[str]) -> bool:
    if not err:
        return False
    low = err.lower()
    return any(
        needle in low
        for needle in (
            "session",
            "resume",
            "not found",
            "unknown session",
            "no such",
            "invalid session",
        )
    )


def _run_grok_once(
    prompt: str,
    cwd: Path,
    emit: Callable[[str], None],
    session_id: Optional[str],
    dangerously_skip: bool,
    permission_mode: str,
    timeout: int,
    model: str = "",
    reasoning_effort: str = "",
    recorder=None,
    budget_tokens: Optional[int] = None,
) -> dict:
    """Single attempt at a headless Grok turn. See ``run_grok``."""
    cmd = build_grok_cmd(
        prompt,
        cwd,
        session_id=session_id,
        dangerously_skip=dangerously_skip,
        permission_mode=permission_mode,
        model=model,
        reasoning_effort=reasoning_effort,
        budget_tokens=budget_tokens,
    )
    return _run_cli_once(
        cmd,
        cwd,
        emit,
        session_id,
        timeout,
        driver_label="Grok",
        stream_kind="grok",
        recorder=recorder,
    )


def run_grok(
    prompt: str,
    cwd: Path,
    on_line: Optional[Callable[[str], None]] = None,
    session_id: Optional[str] = None,
    permission_mode: str = "acceptEdits",
    dangerously_skip: bool = False,
    timeout: int = PLAN_TIMEOUT,
    model: str = "",
    reasoning_effort: str = "",
    recorder=None,
    budget_tokens: Optional[int] = None,
) -> dict:
    """Run one headless Grok turn, streaming progress via ``on_line``.

    Uses ``--output-format streaming-json`` so we can surface Grok's narration
    live. Returns ``{sessionId, error}``. Auth is Grok's own (cached OAuth or
    ``XAI_API_KEY``) — no key wiring is needed here.

    If a stored ``session_id`` fails to resume (e.g. leftover Claude session
    ids from before the swap), we retry once with a fresh session.

    ``budget_tokens`` (when set) wraps the prompt as ``/goal … --budget N``.
    """
    emit = on_line or (lambda _s: None)
    result = _run_grok_once(
        prompt,
        cwd,
        emit,
        session_id,
        dangerously_skip,
        permission_mode,
        timeout,
        model=model,
        reasoning_effort=reasoning_effort,
        recorder=recorder,
        budget_tokens=budget_tokens,
    )
    if result["error"] and session_id and _looks_like_session_error(result["error"]):
        emit("Session resume failed — starting a fresh Grok session…")
        if recorder is not None:
            recorder.retry()
        result = _run_grok_once(
            prompt,
            cwd,
            emit,
            None,
            dangerously_skip,
            permission_mode,
            timeout,
            model=model,
            reasoning_effort=reasoning_effort,
            recorder=recorder,
            budget_tokens=budget_tokens,
        )
    return result


def run_agent(
    prompt: str,
    cwd: Path,
    on_line: Optional[Callable[[str], None]] = None,
    session_id: Optional[str] = None,
    permission_mode: Optional[str] = None,
    dangerously_skip: bool = False,
    timeout: int = PLAN_TIMEOUT,
    settings: Optional[dict] = None,
    recorder=None,
    apply_build_budget: bool = False,
    build_budget_usd: Any = _BUDGET_UNSET,
) -> dict:
    """Run one Grok Build agent turn.

    All plan/build/refine/improve/consolidate jobs call this. Settings are
    normalized to Grok-only even if a stale Claude blob is passed in.

    When ``apply_build_budget`` is True, a dollar budget is resolved (per-build
    override or ``grok.maxBuildBudgetUsd``) and converted to tokens for
    ``/goal --budget``.
    """
    cfg = normalize_settings(settings if settings is not None else load_settings())
    emit = on_line or (lambda _s: None)
    g = cfg["grok"]
    emit(f"Driver: Grok Build ({g.get('model') or 'default'})")
    budget_tokens: Optional[int] = None
    if apply_build_budget:
        budget_tokens = resolve_build_budget_tokens(
            override=build_budget_usd, settings=cfg
        )
        if budget_tokens is not None:
            # Recover the dollar figure for the log line (override or settings).
            usd_src = (
                build_budget_usd
                if build_budget_usd is not _BUDGET_UNSET
                else g.get("maxBuildBudgetUsd")
            )
            usd_amt = parse_budget_usd(usd_src)
            if usd_amt is not None:
                emit(
                    f"Build budget: ${usd_amt:g} ≈ {budget_tokens:,} tokens "
                    f"(goal --budget)"
                )
            else:
                emit(f"Build budget: {budget_tokens:,} tokens (goal --budget)")
        else:
            emit("Build budget: unlimited")
    if recorder is not None:
        recorder.update(
            driver=DRIVER_GROK,
            driverLabel="Grok Build",
            model=g.get("model") or "",
            effort=g.get("reasoningEffort") or "",
            permissionMode=permission_mode or g.get("permissionMode") or "acceptEdits",
        )
    return run_grok(
        prompt,
        cwd,
        on_line=emit,
        session_id=session_id,
        permission_mode=permission_mode or g.get("permissionMode") or "acceptEdits",
        dangerously_skip=dangerously_skip,
        timeout=timeout,
        model=g.get("model") or "",
        reasoning_effort=g.get("reasoningEffort") or "",
        recorder=recorder,
        budget_tokens=budget_tokens,
    )
