"""Agent driver for Concept Factory.

Each topic card gets its own subfolder under ``workspace/`` and its own
headless **Grok Build** instance. We never point the agent at the meta-agent
template folder (that would blow up token usage across ~100 parallel runs);
instead the house style is condensed into the prompt below.

This module is a *pure driver*: it knows how to run the Grok CLI and build
prompts. Topic state lives in main.py; global driver settings live in
``settings.json`` next to this module.

Claude Code was removed as a selectable factory driver; stale
``driver: "claude"`` settings coerce to Grok on load/save.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Sentinel: build job did not pass an explicit per-build budget override
# (fall back to settings.grok.maxBuildBudgetUsd). Distinct from None, which
# means "unlimited for this build".
_BUDGET_UNSET: Any = object()

TEMPLATE_DIR = Path(__file__).parents[1] / "meta-agent" / "template"

WORKSPACE = Path(__file__).parent / "workspace"
WORKSPACE.mkdir(exist_ok=True)

# Path to the Grok CLI. Override with GROK_BIN if it isn't on PATH
# (common install: ~/.grok/bin/grok).
GROK_BIN = os.environ.get("GROK_BIN") or shutil.which("grok") or "grok"
# Retained for legacy helpers/tests only — not used by factory jobs.
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"

# Global factory settings (Grok options). Separate from data.json so topic
# cards and driver config don't thrash the same lock/file.
SETTINGS_FILE = Path(__file__).parent / "settings.json"
_settings_lock = threading.Lock()

DRIVER_GROK = "grok"
# Historical id only (run history labels); never selected as active driver.
DRIVER_CLAUDE = "claude"
DRIVERS = (DRIVER_GROK,)

DEFAULT_SETTINGS: Dict[str, Any] = {
    "driver": DRIVER_GROK,
    "grok": {
        # Empty → follow the CLI's currently selected / default model.
        "model": "",
        "permissionMode": "acceptEdits",
        "reasoningEffort": "",  # empty | low | medium | high
        # Max $ spend per Approve & build (Grok goal --budget). Empty = unlimited.
        "maxBuildBudgetUsd": "",
    },
}

# Approximate blended tokens per USD for Grok Build goal budgets.
# Observed factory runs land near ~0.9M tok/$; we use a clean 1M so $1 → 1_000_000
# tokens. Not exact billing parity (cache hits / model mix shift the real rate).
TOKENS_PER_USD = 1_000_000

# Historical Claude bootstrap default (legacy helpers only).
_CLAUDE_BOOTSTRAP_MODELS = frozenset({"", "sonnet"})


def default_settings() -> dict:
    """Deep copy of factory defaults (safe to mutate)."""
    return json.loads(json.dumps(DEFAULT_SETTINGS))


def parse_budget_usd(value: Any) -> Optional[float]:
    """Normalize a user/API budget value to a positive dollar amount, or None.

    Empty string, None, 0, negative, non-finite, and unparseable values all
    mean **unlimited** (no token cap).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "")
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount) or amount <= 0:
        return None
    return amount


def dollars_to_budget_tokens(usd: Any) -> Optional[int]:
    """Convert a dollar build budget to Grok ``/goal --budget`` tokens.

    Returns ``None`` when the budget is empty/unset/non-positive (unlimited —
    callers must omit ``--budget``). Positive dollars yield a positive int
    token cap via :data:`TOKENS_PER_USD`.
    """
    amount = parse_budget_usd(usd)
    if amount is None:
        return None
    tokens = int(math.floor(amount * TOKENS_PER_USD))
    return tokens if tokens > 0 else None


def format_budget_usd_for_storage(value: Any) -> str:
    """Persist budget as empty string (unlimited) or a clean numeric string."""
    amount = parse_budget_usd(value)
    if amount is None:
        return ""
    # Avoid noisy floats: 5.0 → "5", 0.5 → "0.5"
    if amount == int(amount):
        return str(int(amount))
    return f"{amount:.4f}".rstrip("0").rstrip(".")


def format_grok_goal_prompt(objective: str, budget_tokens: int) -> str:
    """Wrap a build objective as a Grok ``/goal`` with a token budget.

    Grok's slash-command contract is::

        /goal <objective> [--budget <tokens>]

    Headless ``grok -p`` accepts the same prompt text; the goal loop then
    enforces the token cap.
    """
    obj = (objective or "").strip()
    tokens = int(budget_tokens)
    if tokens <= 0:
        return obj
    if not obj:
        return f"/goal --budget {tokens}"
    return f"/goal {obj} --budget {tokens}"


def resolve_build_budget_tokens(
    override: Any = _BUDGET_UNSET,
    settings: Optional[dict] = None,
) -> Optional[int]:
    """Resolve the token cap for a Grok build.

    * If ``override`` is provided (including ``None`` / empty), it wins —
      ``None``/empty means unlimited for this build.
    * Otherwise read ``settings.grok.maxBuildBudgetUsd`` (loaded settings when
      ``settings`` is omitted).
    """
    if override is not _BUDGET_UNSET:
        return dollars_to_budget_tokens(override)
    cfg = normalize_settings(settings if settings is not None else load_settings())
    return dollars_to_budget_tokens((cfg.get("grok") or {}).get("maxBuildBudgetUsd"))


def normalize_settings(raw: Optional[dict] = None) -> dict:
    """Merge partial/unknown settings into a complete, valid settings object.

    Grok Build is the only factory driver. Any ``driver`` value (including
    stale ``claude`` / ``Claude Code``) is coerced to ``grok``. A legacy
    ``claude`` section in stored JSON is ignored and never re-emitted.
    """
    base = default_settings()
    if not raw or not isinstance(raw, dict):
        return base
    # Always Grok — drop dual-driver selection entirely.
    base["driver"] = DRIVER_GROK
    section = raw.get("grok")
    if isinstance(section, dict):
        for k, v in section.items():
            if k not in base["grok"]:
                continue
            # maxBuildBudgetUsd: null/None clears to unlimited ("").
            if k == "maxBuildBudgetUsd":
                base["grok"][k] = format_budget_usd_for_storage(v)
                continue
            base["grok"][k] = v if v is not None else base["grok"][k]
    # Final normalize of budget field even when section was absent/partial.
    base["grok"]["maxBuildBudgetUsd"] = format_budget_usd_for_storage(
        base["grok"].get("maxBuildBudgetUsd")
    )
    # Never persist deprecated Claude fields on the normalized object.
    base.pop("claude", None)
    return base


def load_settings() -> dict:
    with _settings_lock:
        if SETTINGS_FILE.is_file():
            try:
                data = json.loads(SETTINGS_FILE.read_text())
                return normalize_settings(data if isinstance(data, dict) else None)
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        return default_settings()


def save_settings(settings: dict) -> dict:
    cleaned = normalize_settings(settings)
    with _settings_lock:
        SETTINGS_FILE.write_text(json.dumps(cleaned, indent=2) + "\n")
    return cleaned


# --- Settings option catalog (live discovery + TTL cache) -------------------
# Dropdown options come from real CLIs / their config files — never a hard-coded
# model ID list in the frontend.
#
# TTL cache: discovery can take ~1s (Claude PTY). Cache results so settings open
# is fast after the first poll; force=True / refresh busts the cache.
# Concurrent callers coalesce onto one in-flight discovery.
#
# Sources:
#   Grok current  → ~/.grok/config.toml [models].default
#   Grok models   → ~/.grok/models_cache.json (CLI's own cache), else `grok models`
#   Claude current → ~/.claude/settings.json "model" + PTY /model
#   Claude models  → `claude -p /model` (PTY; full Available list)
#   Enums         → `grok --help` / `claude --help` in parallel
#
# Probes within a driver run in parallel; drivers run in parallel too so wall
# time ≈ max(probe) rather than sum.

import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Wall-clock for a single discovery subprocess.
CATALOG_CLI_TIMEOUT = int(os.environ.get("CF_SETTINGS_CATALOG_TIMEOUT", "90"))
# How long a successful catalog poll is reused (seconds). Discovery is now
# file-first (~ms), so a short TTL is cheap and keeps the widget in step with
# changes made directly in the CLIs (e.g. /model in an interactive session).
CATALOG_TTL_SECONDS = int(os.environ.get("CF_SETTINGS_CATALOG_TTL", "15"))
# Claude's full Available: list needs a ~1s headless PTY session (`-p /model`).
# File-first policy: routine polls NEVER spawn it — current model comes from
# ~/.claude/settings.json and the model list from cached `--help` aliases.
# The PTY probe runs only on deep refresh (refresh button / force=True), or
# always/never when CF_SETTINGS_CLAUDE_PTY is explicitly 1/0.
_claude_pty_env = os.environ.get("CF_SETTINGS_CLAUDE_PTY", "").strip().lower()


def _use_claude_pty(deep: bool) -> bool:
    if _claude_pty_env in ("1", "true", "yes", "on"):
        return True
    if _claude_pty_env in ("0", "false", "no", "off"):
        return False
    return deep


# Retained for backwards compat with any external readers.
CATALOG_USE_CLAUDE_PTY = _use_claude_pty(False)

_catalog_lock = threading.Lock()
_catalog_cache: Optional[dict] = None
_catalog_cache_fetched_at: float = 0.0
_catalog_inflight: Optional[threading.Event] = None
_catalog_inflight_result: Optional[dict] = None
_catalog_inflight_error: Optional[BaseException] = None
# Test / observability: number of times we actually spawn a discovery CLI.
_cli_spawn_count = 0


def reset_cli_spawn_count() -> None:
    """Test helper: zero the discovery-spawn counter."""
    global _cli_spawn_count
    _cli_spawn_count = 0


def get_cli_spawn_count() -> int:
    """How many discovery subprocesses have been launched (process lifetime)."""
    return _cli_spawn_count


def _run_discovery_cli_pipes(argv: List[str], timeout: int) -> dict:
    """Capture stdout/stderr via plain pipes (works for ``grok models``, ``--help``)."""
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "argv": list(argv),
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
        "returncode": proc.returncode,
        "error": None,
        "pty": False,
    }


def _run_discovery_cli_pty(argv: List[str], timeout: int) -> dict:
    """Run under a pseudo-TTY.

    Claude Code's headless ``/model`` listing fails with a spurious API 400 when
    stdout is a plain pipe (``model: String should have at most 256 characters``)
    but succeeds when attached to a PTY — same argv. Use this for that probe.
    """
    import pty
    import select

    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen(
            argv,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
    finally:
        os.close(slave)

    chunks: List[bytes] = []
    deadline = _time.time() + timeout
    try:
        while _time.time() < deadline:
            remaining = max(0.05, deadline - _time.time())
            ready, _, _ = select.select([master], [], [], min(0.5, remaining))
            if master in ready:
                try:
                    data = os.read(master, 8192)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
            if proc.poll() is not None:
                # Drain residual output.
                while True:
                    ready, _, _ = select.select([master], [], [], 0.05)
                    if master not in ready:
                        break
                    try:
                        data = os.read(master, 8192)
                    except OSError:
                        data = b""
                    if not data:
                        break
                    chunks.append(data)
                break
        else:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
            return {
                "argv": list(argv),
                "stdout": b"".join(chunks).decode("utf-8", errors="replace"),
                "stderr": "",
                "returncode": -1,
                "error": f"timed out after {timeout}s",
                "pty": True,
            }
        rc = proc.wait(timeout=5)
    finally:
        try:
            os.close(master)
        except OSError:
            pass

    text = b"".join(chunks).decode("utf-8", errors="replace")
    # Strip common PTY noise (script ^D, CR).
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)  # ANSI CSI
    return {
        "argv": list(argv),
        "stdout": text,
        "stderr": "",
        "returncode": rc if rc is not None else -1,
        "error": None,
        "pty": True,
    }


def run_discovery_cli(
    argv: List[str],
    timeout: Optional[int] = None,
    *,
    use_pty: bool = False,
) -> dict:
    """Spawn a discovery CLI and return {argv, stdout, stderr, returncode, error}.

    This is the single spawn seam tests spy on to prove live polling vs cache hits.
    Set ``use_pty=True`` for Claude's headless ``/model`` probe (pipe breaks it).
    """
    global _cli_spawn_count
    _cli_spawn_count += 1
    t = CATALOG_CLI_TIMEOUT if timeout is None else timeout
    try:
        if use_pty:
            return _run_discovery_cli_pty(argv, t)
        return _run_discovery_cli_pipes(argv, t)
    except FileNotFoundError as e:
        return {
            "argv": list(argv),
            "stdout": "",
            "stderr": "",
            "returncode": 127,
            "error": f"CLI not found: {e}",
            "pty": use_pty,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "argv": list(argv),
            "stdout": (e.stdout or "") if isinstance(e.stdout, str) else "",
            "stderr": (e.stderr or "") if isinstance(e.stderr, str) else "",
            "returncode": -1,
            "error": f"timed out after {t}s",
            "pty": use_pty,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "argv": list(argv),
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "error": str(e),
            "pty": use_pty,
        }


def _opt(value: str, label: Optional[str] = None, **extra: Any) -> dict:
    return {"value": value, "label": label if label is not None else value, **extra}


def parse_grok_models_output(text: str) -> dict:
    """Parse ``grok models`` stdout into models + concrete current/default id.

    No empty "CLI default" placeholder — the current selection is the real
    default model id (e.g. ``grok-4.5``).
    """
    models: List[dict] = []
    default: Optional[str] = None
    # Lines like: "  - grok-4.3" or "  * grok-4.5 (default)"
    line_re = re.compile(
        r"^\s*([-*•])\s+(\S+?)(?:\s+\(default\))?\s*$", re.IGNORECASE
    )
    # Also: "Default model: grok-4.5"
    dm = re.search(r"(?im)^\s*Default model:\s*(\S+)\s*$", text or "")
    if dm:
        default = dm.group(1).strip()
    for line in (text or "").splitlines():
        m = line_re.match(line)
        if not m:
            continue
        marker, mid = m.group(1), m.group(2).strip()
        is_default = marker == "*" or "(default)" in line.lower()
        if is_default:
            default = mid
        models.append(
            _opt(
                mid,
                f"{mid} (current)" if is_default or mid == default else mid,
                default=bool(is_default or mid == default),
            )
        )
    # Deduplicate preserving order
    seen = set()
    uniq: List[dict] = []
    for o in models:
        if o["value"] in seen:
            continue
        seen.add(o["value"])
        if default and o["value"] == default:
            o["default"] = True
            o["label"] = f"{o['value']} (current)"
        uniq.append(o)
    return {
        "models": uniq,
        "default": default or "",
        "currentModel": default or (uniq[0]["value"] if uniq else ""),
    }


def map_claude_current_to_alias(
    current_label: str,
    available: List[str],
    settings_model: str = "",
) -> str:
    """Map CLI 'Current model: Fable 5' / settings ids onto a selectable alias.

    Prefer exact available matches, then settings.json model, then label tokens
    (``Fable 5`` → ``fable``, ``Haiku 4.5`` → ``haiku``).
    """
    values = [v for v in available if v]
    value_set = set(values)
    settings_model = (settings_model or "").strip()
    current_label = (current_label or "").strip()

    if settings_model and settings_model in value_set:
        return settings_model

    # settings may store full ids: claude-fable-5[1m] → fable[1m] / fable
    if settings_model:
        low = settings_model.lower()
        wants_1m = "[1m]" in low
        # Prefer longer alias matches (fable[1m] before fable); if settings
        # encodes a 1m context window, prefer *[1m] aliases first.
        ranked = sorted(
            values,
            key=lambda v: (
                0 if wants_1m and "[1m]" in v.lower() else 1,
                -len(v),
            ),
        )
        for v in ranked:
            vl = v.lower()
            base = vl.replace("[1m]", "")
            if vl in low or low in vl:
                return v
            # claude-fable-5[1m] contains "fable"
            if base and base in low:
                if wants_1m and "[1m]" not in vl:
                    # keep looking for a 1m variant first
                    continue
                return v
        # Strip provider prefix / version noise
        core = re.sub(r"^claude-", "", low)
        core = re.sub(r"\[1m\]", "", core)
        core = re.sub(r"-\d.*$", "", core)  # fable-5 → fable (approx)
        for v in ranked:
            base = v.lower().replace("[1m]", "")
            if base and (base in core or core.startswith(base)):
                return v

    if not current_label:
        return ""

    # Exact available match on full label
    if current_label in value_set:
        return current_label

    # "Fable 5" / "Haiku 4.5" / "Sonnet 5" → first token
    first = current_label.split()[0].strip().lower()
    # Prefer 1m variant only when settings said so (handled above); label alone → base
    if first in value_set:
        return first

    # Label contains alias
    low_label = current_label.lower()
    for v in sorted(values, key=lambda x: len(x), reverse=True):
        if v.lower() in low_label:
            return v

    return first if first else ""


def parse_claude_models_output(text: str, settings_model: str = "") -> dict:
    """Parse headless ``claude -p /model`` text into options + **current** alias.

    Typical output:
      Current model: Fable 5
      Usage: /model <name>. Available: sonnet, opus, haiku, fable, ...
    """
    models: List[dict] = []
    text = text or ""
    cm = re.search(r"(?im)Current model:\s*(.+?)\s*$", text)
    current_label = cm.group(1).strip() if cm else ""

    avail = re.search(r"(?is)Available:\s*(.+?)(?:\.\s*$|\n|$)", text)
    if avail:
        blob = avail.group(1)
        blob = re.sub(r"(?i)\bor a full model ID\b.*$", "", blob).strip()
        parts = [p.strip().strip(".") for p in blob.split(",") if p.strip()]
        cleaned: List[str] = []
        for p in parts:
            p = re.sub(r"(?i)^\s*or\s+", "", p).strip()
            if not p:
                continue
            if not re.match(r"^[\w.\[\]/-]+$", p):
                continue
            cleaned.append(p)
        for mid in cleaned:
            models.append(_opt(mid))
    if not models:
        for m in re.finditer(r"(?m)^\s*[-*]\s+([A-Za-z0-9_./\[\]-]+)\s*$", text):
            models.append(_opt(m.group(1)))

    seen = set()
    uniq: List[dict] = []
    for o in models:
        if o["value"] in seen:
            continue
        seen.add(o["value"])
        uniq.append(o)

    values = [o["value"] for o in uniq]
    current = map_claude_current_to_alias(current_label, values, settings_model)
    # Mark current in labels
    for o in uniq:
        if current and o["value"] == current:
            o["default"] = True
            o["label"] = f"{o['value']} (current)"

    return {
        "models": uniq,
        "default": current,
        "currentModel": current,
        "currentLabel": current_label,
    }


def parse_help_possible_values(help_text: str, flag: str) -> List[str]:
    """Extract enum values for a CLI flag from ``--help`` text.

    Handles:
      --permission-mode <MODE> ... [possible values: a, b, c]
      --permission-mode <mode> (choices: "a", "b", "c")
      --effort <level> (low, medium, high, xhigh, max)
    """
    text = help_text or ""
    # Find the flag section (from the flag to the next --flag or end)
    # Flags may appear as --foo or --foo <ARG>
    flag_esc = re.escape(flag)
    # Match flag line + following indented lines until next option
    m = re.search(
        rf"(?ims)^\s*{flag_esc}\b.*?(?=^\s+--[a-z]|\Z)",
        text,
    )
    section = m.group(0) if m else ""
    if not section:
        # Sometimes help wraps and flag is alone on one line with values on next
        m2 = re.search(
            rf"(?ims)^\s*{flag_esc}\b.*$",
            text,
        )
        if m2:
            start = m2.start()
            section = text[start : start + 600]

    # [possible values: a, b, c]
    pv = re.search(r"\[possible values:\s*([^\]]+)\]", section, re.I)
    if pv:
        return [x.strip().strip("\"'") for x in pv.group(1).split(",") if x.strip()]

    # (choices: "a", "b", "c") — may span lines
    ch = re.search(r"\(choices:\s*([^)]+)\)", section, re.I | re.S)
    if ch:
        raw = ch.group(1)
        return [x.strip().strip("\"'") for x in re.split(r"[,\n]", raw) if x.strip().strip("\"'")]

    # Parenthetical bare list after effort-like flags: (low, medium, high, xhigh, max)
    bare = re.search(
        r"\(([a-z][a-z0-9_-]*(?:\s*,\s*[a-z][a-z0-9_-]*)+)\)",
        section,
        re.I,
    )
    if bare:
        return [x.strip() for x in bare.group(1).split(",") if x.strip()]

    return []


def parse_help_effort_levels(help_text: str) -> List[str]:
    """Claude ``--effort`` levels from help (low, medium, high, xhigh, max)."""
    vals = parse_help_possible_values(help_text, "--effort")
    if vals:
        return vals
    # Broader scan: "Effort level ... (low, medium, high, xhigh, max)"
    m = re.search(
        r"(?is)--effort\b.*?(\(\s*low\s*,\s*medium\s*,\s*high[^)]*\))",
        help_text or "",
    )
    if m:
        inner = m.group(1).strip("()")
        return [x.strip() for x in inner.split(",") if x.strip()]
    return []


def _labelize(value: str) -> str:
    if not value:
        return "Default"
    # acceptEdits → Accept edits
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    spaced = spaced.replace("-", " ").replace("_", " ")
    return spaced[:1].upper() + spaced[1:] if spaced else value


def _read_grok_config_default() -> str:
    """Sticky default from ``~/.grok/config.toml`` ``[models] default = "…"``."""
    path = Path.home() / ".grok" / "config.toml"
    try:
        text = path.read_text()
    except OSError:
        return ""
    # Prefer [models] section default=
    in_models = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_models = stripped.lower() == "[models]"
            continue
        if in_models:
            m = re.match(r'default\s*=\s*"([^"]+)"', stripped)
            if m:
                return m.group(1).strip()
            m = re.match(r"default\s*=\s*'([^']+)'", stripped)
            if m:
                return m.group(1).strip()
    # Fallback: first default = anywhere
    m = re.search(r'(?m)^\s*default\s*=\s*"([^"]+)"', text)
    return m.group(1).strip() if m else ""


def _read_grok_models_cache() -> dict:
    """Parse ``~/.grok/models_cache.json`` (Grok's own on-disk model list).

    Returns {models: [{value,label}], default: str} or empty dict on miss.
    """
    path = Path.home() / ".grok" / "models_cache.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    raw = data.get("models") if isinstance(data, dict) else None
    if not isinstance(raw, dict) or not raw:
        return {}
    models: List[dict] = []
    for mid in raw.keys():
        mid = str(mid).strip()
        if mid:
            models.append(_opt(mid))
    cfg_default = _read_grok_config_default()
    default = cfg_default
    if not default:
        # Prefer non-hidden agent models; fall back to first key
        default = next((m["value"] for m in models if m["value"].startswith("grok-")), "")
        if not default and models:
            default = models[0]["value"]
    for o in models:
        if default and o["value"] == default:
            o["default"] = True
            o["label"] = f"{o['value']} (current)"
    return {
        "models": models,
        "default": default,
        "currentModel": default,
        "source": "models_cache.json",
    }


# --- Disk-cached `--help` (enums + model aliases without spawning) ----------
# Help output only changes when the CLI binary changes, so cache it on disk
# keyed by the binary's (path, mtime, size). Steady-state discovery then reads
# only files: ~/.claude/settings.json, ~/.grok/{config.toml,models_cache.json},
# and this cache — zero process spawns, ~ms wall time. A deep refresh
# (refresh button) bypasses the cache and re-runs `--help`.

_HELP_CACHE_FILE = Path(__file__).parent / ".cli_help_cache.json"
_help_cache_lock = threading.Lock()

# The full Claude model list (sonnet/opus/haiku/fable/...) only appears in the
# PTY `/model` "Available:" output, which is deep-only. `claude --help` does not
# enumerate every alias (notably haiku), so shallow discovery would drop models
# the user actually has. We persist the last deep-probed list to disk, keyed by
# the same binary fingerprint, so shallow discovery serves the complete list
# with zero spawns and a deep refresh keeps it current.
_MODEL_LIST_CACHE_FILE = Path(__file__).parent / ".cli_model_list_cache.json"
_model_list_lock = threading.Lock()


def _bin_fingerprint(bin_path: str) -> Optional[dict]:
    resolved = shutil.which(bin_path) or bin_path
    try:
        st = os.stat(resolved)
    except OSError:
        return None
    return {"path": resolved, "mtime": st.st_mtime, "size": st.st_size}


def _load_help_cache() -> dict:
    try:
        data = json.loads(_HELP_CACHE_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _load_model_list_cache() -> dict:
    try:
        data = json.loads(_MODEL_LIST_CACHE_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def cached_claude_models(bin_path: str = None) -> List[str]:
    """Last deep-probed Claude model aliases for this binary, or []."""
    fp = _bin_fingerprint(bin_path or CLAUDE_BIN)
    if fp is None:
        return []
    with _model_list_lock:
        entry = _load_model_list_cache().get(fp["path"])
    if (
        isinstance(entry, dict)
        and entry.get("mtime") == fp["mtime"]
        and entry.get("size") == fp["size"]
        and isinstance(entry.get("models"), list)
    ):
        return [m for m in entry["models"] if isinstance(m, str)]
    return []


def save_claude_model_list(models: List[str], bin_path: str = None) -> None:
    """Persist deep-probed model aliases keyed by binary fingerprint (best-effort)."""
    models = [m for m in (models or []) if isinstance(m, str) and m.strip()]
    if not models:
        return
    fp = _bin_fingerprint(bin_path or CLAUDE_BIN)
    if fp is None:
        return
    with _model_list_lock:
        cache = _load_model_list_cache()
        cache[fp["path"]] = {"mtime": fp["mtime"], "size": fp["size"], "models": models}
        try:
            tmp = _MODEL_LIST_CACHE_FILE.with_name(_MODEL_LIST_CACHE_FILE.name + ".tmp")
            tmp.write_text(json.dumps(cache) + "\n")
            tmp.replace(_MODEL_LIST_CACHE_FILE)
        except OSError:
            pass


def get_cli_help(bin_path: str, refresh: bool = False) -> dict:
    """Return ``--help`` text for a CLI, from disk cache when the binary is
    unchanged. Shape matches ``run_discovery_cli`` plus ``cached: bool``."""
    fp = _bin_fingerprint(bin_path)
    if fp is not None and not refresh:
        with _help_cache_lock:
            entry = _load_help_cache().get(fp["path"])
        if (
            isinstance(entry, dict)
            and entry.get("mtime") == fp["mtime"]
            and entry.get("size") == fp["size"]
            and isinstance(entry.get("help"), str)
        ):
            return {
                "argv": [bin_path, "--help"],
                "stdout": entry["help"],
                "stderr": "",
                "returncode": 0,
                "error": None,
                "pty": False,
                "cached": True,
            }
    run = run_discovery_cli([bin_path, "--help"])
    run["cached"] = False
    if fp is not None and run.get("returncode") == 0 and not run.get("error"):
        text = (run.get("stdout") or "") + ("\n" + run["stderr"] if run.get("stderr") else "")
        with _help_cache_lock:
            cache = _load_help_cache()
            cache[fp["path"]] = {"mtime": fp["mtime"], "size": fp["size"], "help": text}
            try:
                tmp = _HELP_CACHE_FILE.with_name(_HELP_CACHE_FILE.name + ".tmp")
                tmp.write_text(json.dumps(cache) + "\n")
                tmp.replace(_HELP_CACHE_FILE)
            except OSError:
                pass  # cache is best-effort
    return run


def discover_grok_options(deep: bool = False) -> dict:
    """Live discovery for Grok Build: models + help enums.

    File-first: models from ``models_cache.json``, current from ``config.toml``,
    enums from disk-cached ``--help``. Steady-state → zero spawns. ``deep=True``
    (refresh button) re-runs ``grok --help``.
    """
    file_models = _read_grok_models_cache()
    cfg_default = _read_grok_config_default()

    def _help() -> dict:
        return get_cli_help(GROK_BIN, refresh=deep)

    def _cli_models() -> dict:
        return run_discovery_cli([GROK_BIN, "models"])

    models_run: Optional[dict] = None
    help_run: dict
    if file_models.get("models"):
        # Parallel: only help (models already from disk)
        help_run = _help()
        parsed = {
            "models": file_models["models"],
            "default": cfg_default or file_models.get("default") or "",
            "currentModel": cfg_default or file_models.get("currentModel") or "",
        }
        # Re-mark current label from config.toml
        for o in parsed["models"]:
            if parsed["currentModel"] and o["value"] == parsed["currentModel"]:
                o["default"] = True
                o["label"] = f"{o['value']} (current)"
            elif o.get("default") and o["value"] != parsed["currentModel"]:
                o["default"] = False
                o["label"] = o["value"]
        models_probe = {
            "argv": ["file", str(Path.home() / ".grok" / "models_cache.json")],
            "returncode": 0,
            "error": None,
            "source": "models_cache.json",
        }
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_models = pool.submit(_cli_models)
            f_help = pool.submit(_help)
            models_run = f_models.result()
            help_run = f_help.result()
        combined_out = (models_run.get("stdout") or "") + "\n" + (models_run.get("stderr") or "")
        parsed = parse_grok_models_output(combined_out)
        if cfg_default:
            parsed["currentModel"] = cfg_default
            parsed["default"] = cfg_default
            for o in parsed["models"]:
                if o["value"] == cfg_default:
                    o["default"] = True
                    o["label"] = f"{o['value']} (current)"
                else:
                    o["default"] = False
                    if o["label"].endswith(" (current)"):
                        o["label"] = o["value"]
        models_probe = {
            "argv": models_run.get("argv"),
            "returncode": models_run.get("returncode"),
            "error": models_run.get("error"),
            "source": "grok models",
        }

    help_text = (help_run.get("stdout") or "") + "\n" + (help_run.get("stderr") or "")
    perm = parse_help_possible_values(help_text, "--permission-mode")
    reasoning = parse_help_possible_values(help_text, "--reasoning-effort")
    err_parts = [x for x in ((models_run or {}).get("error"), help_run.get("error")) if x]
    if (
        models_run
        and models_run.get("returncode") not in (0, None)
        and not parsed["models"]
    ):
        err_parts.append(
            f"grok models exited {models_run.get('returncode')}: "
            f"{(models_run.get('stderr') or models_run.get('stdout') or '')[-200:]}"
        )
    current = (
        cfg_default
        or parsed.get("currentModel")
        or parsed.get("default")
        or ""
    )
    return {
        "driver": DRIVER_GROK,
        "models": parsed["models"],
        "defaultModel": parsed.get("default") or current,
        "currentModel": current,
        "permissionModes": [_opt(v, _labelize(v)) for v in perm],
        "reasoningEfforts": [_opt("", "Default")]
        + [_opt(v, _labelize(v)) for v in reasoning],
        "error": "; ".join(err_parts) if err_parts and not parsed["models"] else None,
        "probes": {
            "models": models_probe,
            "help": {
                "argv": help_run.get("argv"),
                "returncode": help_run.get("returncode"),
                "error": help_run.get("error"),
            },
            "configDefault": cfg_default,
        },
    }


def _claude_models_from_help(help_text: str) -> List[str]:
    """Secondary source: model aliases mentioned in ``claude --help`` examples."""
    # e.g. 'fable', 'opus', or 'sonnet'  /  'claude-fable-5'
    found: List[str] = []
    for m in re.finditer(
        r"['\"]((?:claude-)?(?:sonnet|opus|haiku|fable|best)[A-Za-z0-9_.\[\]-]*)['\"]",
        help_text or "",
        re.I,
    ):
        mid = m.group(1)
        if mid not in found:
            found.append(mid)
    return found


def _read_claude_user_settings_model() -> str:
    """Model id from ``~/.claude/settings.json`` when present (CLI sticky selection)."""
    path = Path.home() / ".claude" / "settings.json"
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            m = data.get("model")
            return str(m).strip() if m else ""
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return ""


def discover_claude_options(deep: bool = False) -> dict:
    """Discovery for Claude Code — file-first.

    **Current model** comes from ``~/.claude/settings.json`` (instant, exactly
    what the CLI persists). **Available models** come from disk-cached
    ``claude --help`` aliases. Steady-state → zero process spawns.

    ``deep=True`` (refresh button / force) additionally runs headless
    ``claude -p /model`` under a PTY (~1s) for the CLI's full Available: list,
    and re-runs ``--help``. CF_SETTINGS_CLAUDE_PTY=1/0 forces the PTY probe
    always/never.
    """
    settings_model = _read_claude_user_settings_model()
    model_argv = [
        CLAUDE_BIN,
        "-p",
        "/model",
        "--output-format",
        "text",
    ]

    def _help() -> dict:
        return get_cli_help(CLAUDE_BIN, refresh=deep)

    def _model_pty() -> dict:
        return run_discovery_cli(model_argv, use_pty=True)

    model_run: Optional[dict] = None
    if not _use_claude_pty(deep):
        help_run = _help()
        combined = ""
        models_probe = {
            "argv": ["file+help", "settings.json", "claude --help"],
            "returncode": 0,
            "error": None,
            "pty": False,
            "skipped": True,
        }
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_model = pool.submit(_model_pty)
            f_help = pool.submit(_help)
            model_run = f_model.result()
            help_run = f_help.result()
        combined = (model_run.get("stdout") or "") + "\n" + (model_run.get("stderr") or "")
        models_probe = {
            "argv": model_run.get("argv"),
            "returncode": model_run.get("returncode"),
            "error": model_run.get("error"),
            "pty": model_run.get("pty"),
        }

    if combined.strip().startswith("{"):
        try:
            evt = json.loads(combined.strip().splitlines()[0])
            if isinstance(evt, dict) and evt.get("result"):
                combined = str(evt["result"])
        except (json.JSONDecodeError, ValueError):
            pass
    parsed = parse_claude_models_output(combined, settings_model=settings_model)
    help_text = (help_run.get("stdout") or "") + "\n" + (help_run.get("stderr") or "")
    # Prefer settings.json as source of truth for *current* (file is what CLI persists).
    help_models = _claude_models_from_help(help_text)
    if not parsed["models"]:
        if help_models:
            current = map_claude_current_to_alias(
                "", help_models, settings_model
            ) or (help_models[0] if help_models else "")
            parsed = {
                "models": [_opt(m) for m in help_models],
                "default": current,
                "currentModel": current,
                "currentLabel": "",
            }
    # Merge help aliases into list so we never lose documented models.
    if help_models:
        have = {o["value"] for o in parsed["models"]}
        for m in help_models:
            if m not in have:
                parsed["models"].append(_opt(m))
                have.add(m)
    if deep:
        # Deep probe saw the full "Available:" list — persist it so shallow
        # polls can serve the complete set (incl. haiku) without spawning.
        save_claude_model_list([o["value"] for o in parsed["models"]])
    else:
        # Shallow: fold in the last deep-probed list so models absent from
        # --help (e.g. haiku) don't disappear between refreshes.
        have = {o["value"] for o in parsed["models"]}
        for m in cached_claude_models():
            if m not in have:
                parsed["models"].append(_opt(m))
                have.add(m)
    # Current: settings.json wins when present.
    if settings_model:
        values = [o["value"] for o in parsed.get("models") or []]
        mapped = map_claude_current_to_alias(
            parsed.get("currentLabel") or "", values, settings_model
        )
        if mapped:
            parsed["currentModel"] = mapped
            parsed["default"] = mapped
        elif settings_model not in values:
            # Full id not in list — still surface it as selected + option.
            parsed["models"].insert(0, _opt(settings_model, f"{settings_model} (current)"))
            parsed["currentModel"] = settings_model
            parsed["default"] = settings_model
    elif not parsed.get("currentModel"):
        values = [o["value"] for o in parsed.get("models") or []]
        parsed["currentModel"] = map_claude_current_to_alias(
            parsed.get("currentLabel") or "", values, ""
        )
        parsed["default"] = parsed["currentModel"]

    # Mark current on labels
    cur = parsed.get("currentModel") or ""
    for o in parsed["models"]:
        if cur and o["value"] == cur:
            o["default"] = True
            if "(current)" not in o["label"]:
                o["label"] = f"{o['value']} (current)"

    perm = parse_help_possible_values(help_text, "--permission-mode")
    effort = parse_help_effort_levels(help_text)
    err_parts = [
        x
        for x in ((model_run or {}).get("error"), help_run.get("error"))
        if x
    ]
    if not parsed["models"]:
        detail = ((model_run or {}).get("stderr") or (model_run or {}).get("stdout") or "")[
            -240:
        ]
        err_parts.append(
            f"claude model list empty (rc={(model_run or {}).get('returncode')}): {detail}"
        )
    current = parsed.get("currentModel") or parsed.get("default") or ""
    return {
        "driver": DRIVER_CLAUDE,
        "models": parsed["models"],
        "defaultModel": current,
        "currentModel": current,
        "currentLabel": parsed.get("currentLabel") or "",
        "settingsModel": settings_model,
        "permissionModes": [_opt(v, _labelize(v)) for v in perm],
        "efforts": [_opt("", "Default")] + [_opt(v, _labelize(v)) for v in effort],
        "error": "; ".join(err_parts) if err_parts and not parsed["models"] else None,
        "probes": {
            "models": models_probe,
            "help": {
                "argv": help_run.get("argv"),
                "returncode": help_run.get("returncode"),
                "error": help_run.get("error"),
            },
        },
    }


def resolve_model_selection(
    stored: str,
    cli_current: str,
    *,
    driver: str = DRIVER_GROK,
    follow_cli: bool = False,
) -> str:
    """Choose which model id the settings UI / jobs should use.

    - Empty stored → live CLI current.
    - ``follow_cli=True`` (catalog refresh) → always prefer live CLI current.
    - Otherwise keep an explicit factory override.
    """
    stored = (stored or "").strip()
    cli_current = (cli_current or "").strip()
    if follow_cli and cli_current:
        return cli_current
    # Legacy: historical Claude bootstrap "sonnet" treated as unset if ever passed.
    if driver == DRIVER_CLAUDE and stored in _CLAUDE_BOOTSTRAP_MODELS:
        return cli_current or stored
    if not stored:
        return cli_current
    return stored


def apply_cli_current_to_settings(
    settings: Optional[dict],
    catalog: dict,
    *,
    follow_cli: bool = False,
) -> dict:
    """Return settings with Grok model fields resolved against catalog current."""
    s = normalize_settings(settings)
    grok_cur = (
        (catalog.get("grok") or {}).get("currentModel")
        or (catalog.get("grok") or {}).get("defaultModel")
        or ""
    )
    s["grok"]["model"] = resolve_model_selection(
        s["grok"].get("model") or "",
        grok_cur,
        driver=DRIVER_GROK,
        follow_cli=follow_cli,
    )
    s["cliCurrent"] = {"grok": grok_cur}
    return s


def discover_settings_catalog(deep: bool = False) -> dict:
    """Discover Grok Build options for the settings UI.

    Default is file-first (no spawns when help cache is warm). ``deep=True``
    re-runs ``grok --help`` / model probes. Claude CLI is not queried.
    """
    fetched_at = _time.time()
    grok = discover_grok_options(deep)
    elapsed_ms = round((_time.time() - fetched_at) * 1000, 1)
    return {
        "fetchedAt": fetched_at,
        "fetchedAtIso": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(fetched_at)),
        "elapsedMs": elapsed_ms,
        "ttlSeconds": CATALOG_TTL_SECONDS,
        "source": "live-cli" if deep else "files",
        "deep": deep,
        "cache": "none",
        "grok": grok,
    }


def get_settings_catalog(force: bool = False, deep: Optional[bool] = None) -> dict:
    """Return the settings option catalog, using a TTL memory cache.

    ``force=True`` busts the cache (refresh button) and by default also runs a
    deep Grok probe. Pass ``deep=False`` with force for a cheap file-only
    re-read (used by background revalidation). Concurrent callers share one
    in-flight discovery.
    """
    global _catalog_cache, _catalog_cache_fetched_at
    global _catalog_inflight, _catalog_inflight_result, _catalog_inflight_error

    if deep is None:
        deep = force

    now = _time.time()
    if not force:
        stale_out: Optional[dict] = None
        with _catalog_lock:
            if _catalog_cache is not None:
                age = now - _catalog_cache_fetched_at
                if age < CATALOG_TTL_SECONDS:
                    out = json.loads(json.dumps(_catalog_cache))
                    out["cache"] = "memory"
                    out["ageSeconds"] = round(age, 3)
                    out["ttlSeconds"] = CATALOG_TTL_SECONDS
                    return out
                # Expired: serve stale immediately, revalidate in background
                # (stale-while-revalidate). Refresh coalesces via inflight.
                stale_out = json.loads(json.dumps(_catalog_cache))
                stale_out["cache"] = "memory-stale-revalidating"
                stale_out["ageSeconds"] = round(age, 3)
                stale_out["ttlSeconds"] = CATALOG_TTL_SECONDS
        if stale_out is not None:
            threading.Thread(
                target=lambda: get_settings_catalog(force=True, deep=False),
                daemon=True,
                name="cf-catalog-revalidate",
            ).start()
            return stale_out

    wait_event: Optional[threading.Event] = None
    am_leader = False
    with _catalog_lock:
        if _catalog_inflight is not None:
            wait_event = _catalog_inflight
        else:
            _catalog_inflight = threading.Event()
            _catalog_inflight_result = None
            _catalog_inflight_error = None
            wait_event = _catalog_inflight
            am_leader = True

    if not am_leader:
        assert wait_event is not None
        wait_event.wait(timeout=CATALOG_CLI_TIMEOUT + 30)
        with _catalog_lock:
            if _catalog_inflight_error is not None:
                # Fall through only if we have no usable cache
                if _catalog_cache is not None and not force:
                    out = json.loads(json.dumps(_catalog_cache))
                    out["cache"] = "memory-stale"
                    out["ageSeconds"] = round(_time.time() - _catalog_cache_fetched_at, 3)
                    return out
                if _catalog_inflight_result is not None:
                    out = json.loads(json.dumps(_catalog_inflight_result))
                    out["cache"] = "coalesced"
                    return out
            if _catalog_inflight_result is not None:
                out = json.loads(json.dumps(_catalog_inflight_result))
                out["cache"] = "coalesced"
                return out
            if _catalog_cache is not None:
                out = json.loads(json.dumps(_catalog_cache))
                out["cache"] = "memory"
                out["ageSeconds"] = round(_time.time() - _catalog_cache_fetched_at, 3)
                return out
        return get_settings_catalog(force=force, deep=deep)

    try:
        catalog = discover_settings_catalog(deep=deep)
        catalog["cache"] = "none"
        catalog["ageSeconds"] = 0
        catalog["ttlSeconds"] = CATALOG_TTL_SECONDS
        with _catalog_lock:
            _catalog_cache = catalog
            _catalog_cache_fetched_at = float(catalog.get("fetchedAt") or _time.time())
            _catalog_inflight_result = catalog
            _catalog_inflight_error = None
        return json.loads(json.dumps(catalog))
    except Exception as e:  # noqa: BLE001
        with _catalog_lock:
            _catalog_inflight_error = e
            if _catalog_cache is not None:
                out = json.loads(json.dumps(_catalog_cache))
                out["cache"] = "memory-stale"
                out["error"] = str(e)
                out["ageSeconds"] = round(_time.time() - _catalog_cache_fetched_at, 3)
                return out
        return {
            "fetchedAt": _time.time(),
            "fetchedAtIso": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
            "ttlSeconds": CATALOG_TTL_SECONDS,
            "source": "error",
            "cache": "none",
            "error": str(e),
            "grok": {
                "models": [],
                "permissionModes": [],
                "reasoningEfforts": [],
                "error": str(e),
            },
        }
    finally:
        with _catalog_lock:
            if _catalog_inflight is not None:
                _catalog_inflight.set()
            _catalog_inflight = None


def clear_settings_catalog_cache() -> None:
    """Drop TTL memory cache and any in-flight bookkeeping (tests / refresh)."""
    global _catalog_cache, _catalog_cache_fetched_at
    global _catalog_inflight, _catalog_inflight_result, _catalog_inflight_error
    with _catalog_lock:
        _catalog_cache = None
        _catalog_cache_fetched_at = 0.0
        _catalog_inflight = None
        _catalog_inflight_result = None
        _catalog_inflight_error = None


# --- Widget → CLI write-back (compile settings to CLI state) -----------------
# Settings previously wrote only backend/settings.json (app-local). Write-back
# mirrors the Grok model into ``~/.grok/config.toml`` so the interactive CLI
# agrees with the widget. Set CF_SETTINGS_SYNC_CLI=0 to disable.


def cli_sync_enabled() -> bool:
    v = os.environ.get("CF_SETTINGS_SYNC_CLI", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _write_claude_cli_model(model: str) -> dict:
    """Legacy no-op retained for older tests; factory no longer syncs Claude."""
    path = Path.home() / ".claude" / "settings.json"
    return {
        "driver": DRIVER_CLAUDE,
        "target": str(path),
        "model": model,
        "ok": True,
        "changed": False,
        "error": None,
        "skipped": "claude-deprecated",
    }


def _claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _grok_config_path() -> Path:
    return Path.home() / ".grok" / "config.toml"


def read_current_models() -> dict:
    """Cheap read of the current Grok model from CLI config (no spawn).

    Used by the real-time watcher so a CLI-side ``/model`` change surfaces in
    the widget without a re-poll.
    """
    return {
        "grok": {"currentModel": _read_grok_config_default()},
    }


def current_models_signature() -> str:
    """mtime+size fingerprint of the Grok config file, for change detection."""
    p = _grok_config_path()
    try:
        st = p.stat()
        return f"{p}:{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return f"{p}:-"


def detect_claude_model_overrides(target_model: str) -> List[dict]:
    """Legacy helper — always empty now that Claude is not a factory driver."""
    del target_model
    return []


def _write_grok_cli_model(model: str) -> dict:
    """Persist model into ``~/.grok/config.toml`` ``[models] default`` (line edit)."""
    path = Path.home() / ".grok" / "config.toml"
    action = {"driver": DRIVER_GROK, "target": str(path), "model": model}
    try:
        text = path.read_text() if path.exists() else ""
    except OSError as e:
        return {**action, "ok": False, "changed": False, "error": str(e)}
    if _read_grok_config_default() == model and path.exists():
        return {**action, "ok": True, "changed": False, "error": None}

    lines = text.splitlines()
    out: List[str] = []
    in_models = False
    models_seen = False
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_models and not replaced:
                out.append(f'default = "{model}"')
                replaced = True
            in_models = stripped.lower() == "[models]"
            if in_models:
                models_seen = True
            out.append(line)
            continue
        if in_models and not replaced and re.match(r"^default\s*=", stripped):
            out.append(f'default = "{model}"')
            replaced = True
            continue
        out.append(line)
    if in_models and not replaced:
        out.append(f'default = "{model}"')
        replaced = True
    if not models_seen and not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append("[models]")
        out.append(f'default = "{model}"')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".cf-tmp")
        tmp.write_text("\n".join(out).rstrip("\n") + "\n")
        tmp.replace(path)
        return {**action, "ok": True, "changed": True, "error": None}
    except OSError as e:
        return {**action, "ok": False, "changed": False, "error": str(e)}


def update_catalog_cache_current(driver: str, model: str) -> None:
    """Reflect a write-back in the warm catalog cache so the modal stays
    consistent without paying a re-discovery."""
    if not model:
        return
    with _catalog_lock:
        if _catalog_cache is None:
            return
        d = _catalog_cache.get(driver)
        if not isinstance(d, dict):
            return
        d["currentModel"] = model
        d["defaultModel"] = model
        found = False
        for o in d.get("models") or []:
            if o.get("value") == model:
                o["default"] = True
                o["label"] = f"{model} (current)"
                found = True
            else:
                if o.get("default"):
                    o["default"] = False
                lbl = o.get("label")
                if isinstance(lbl, str) and lbl.endswith(" (current)"):
                    o["label"] = o.get("value")
        if not found:
            models = d.setdefault("models", [])
            models.insert(0, _opt(model, f"{model} (current)", default=True))


def sync_settings_to_cli(settings: dict) -> dict:
    """Compile stored widget settings into Grok CLI state (model write-back).

    Idempotent: writes are no-ops when the CLI file already matches. Returns
    ``{"enabled": bool, "actions": [...]}`` for observability. Never raises.
    """
    if not cli_sync_enabled():
        return {"enabled": False, "actions": []}
    s = normalize_settings(settings)
    actions: List[dict] = []
    grok_model = (s.get("grok") or {}).get("model") or ""
    if grok_model:
        res = _write_grok_cli_model(grok_model)
        actions.append(res)
        if res.get("ok"):
            update_catalog_cache_current(DRIVER_GROK, grok_model)
    return {"enabled": True, "actions": actions}


# Grok is I/O-bound (mostly waiting on the API) but each run spawns a
# process, so we cap concurrency to protect memory and API rate limits.
# 12-core / 18 GB machine → 8 in flight; the rest queue in the executor.
CONCURRENCY = int(os.environ.get("CF_PLAN_CONCURRENCY", "8"))
EXECUTOR = ThreadPoolExecutor(max_workers=CONCURRENCY)

# Per-run wall-clock ceiling (seconds).
PLAN_TIMEOUT = 420
BUILD_TIMEOUT = 1800

PLAN_FILE = "PLAN.md"


def slugify(title: str, taken: set) -> str:
    """kebab-case slug for a topic title, made unique against ``taken``."""
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "topic"
    slug = base
    i = 2
    while slug in taken:
        slug = f"{base}-{i}"
        i += 1
    return slug


def topic_dir(slug: str) -> Path:
    path = WORKSPACE / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_built(slug: str) -> bool:
    """True if a servable production bundle exists on disk for this slug.

    This is the source of truth for "built" — status reconciliation checks the
    workspace rather than trusting a possibly-stale persisted enum.
    """
    return bool(slug) and (WORKSPACE / slug / "dist" / "index.html").is_file()


# --- Prompts ----------------------------------------------------------------
def build_plan_prompt(title: str, context: str, meta_prompt: str) -> str:
    ctx = f"\nEXTRA CONTEXT FROM THE CARD: {context.strip()}" if context.strip() else ""
    meta = (
        f"\nBOARD INTENT (meta prompt steering the whole set): {meta_prompt.strip()}"
        if meta_prompt.strip()
        else ""
    )
    return f"""You are planning ONE single-concept learning micro-app. Do NOT write \
app code. Your only deliverable is a short, reviewable PLAN (like an editor's \
plan mode) for the most *memorable* way to LEARN and TEST the topic below. \
Write it to a file named `{PLAN_FILE}` in your current working directory and nothing else.

TOPIC: {title}{ctx}{meta}

WHAT GETS BUILT LATER (so your plan fits the house pattern — do not build it now):
Each topic becomes a tiny Vite + React + TypeScript + Tailwind app with two tabs:
- LEARN: an interactive "pocket guide" — a centered hero (mono uppercase kicker, \
big title, one-paragraph description), a pill nav of anchor links, then 4-6 numbered \
sections ("01", "02", ...). Prose is tight and second-person; every section carries \
at least one interactive visualization or worked example (never more than ~2 \
paragraphs without something to see or touch). Dark theme (#0b0d12 canvas, \
white/[0.02] panels), ONE accent Tailwind color family per topic, subtle \
framer-motion. Gotchas go in callouts.
- TEST: a game/puzzle that proves the concept stuck. It tests RECALL and \
CONSTRUCTION, not recognition — the player TYPES an answer or PREDICTS output, \
not multiple choice. 10-20 data-driven levels, easy -> hard (first 2-3 teach the \
interface, last 2-3 combine sub-concepts), each level tagged with exactly one \
sub-concept key so results break down by category. Wrong answers return a \
TEACHING reason (e.g. "that fires at minute 10 only, not every 10 minutes"), \
never just "wrong". Validation is a pure function.
Reference mechanics for tone: cron (type the five-field expression; a grid shows \
what it WOULD fire), regex "Pattern Drop" (timed falling patterns; type a string \
that matches), tar (type a command; watch it animate over a file tree). Choose the \
mechanic by asking: what would an expert DO with this concept under mild time \
pressure — write syntax, predict output, or satisfy a constraint? Pick whichever is \
closest to real usage.

`{PLAN_FILE}` MUST be markdown with exactly these sections:
1. `# {title} — Plan`
2. **Repo name** — kebab-case, 1-3 words, concrete (e.g. `hash-tables`, `tcp-handshake`).
3. **One-line description** — the GitHub-style tagline.
4. **Learning angle** — 2-3 sentences: the mental model / "aha" this app builds and why it sticks.
5. **Learn page** — the 4-6 numbered section titles, each with a one-line note on \
its interactive visualization or worked example.
6. **Test game** — an *italicized name*, a one-paragraph mechanic pitch, why that \
mechanic fits THIS concept, the list of sub-concept keys the levels will cover, and \
3 example levels each written as: prompt -> expected answer -> teaching reason for a \
plausible wrong answer.
7. **Accent color** — one Tailwind family (e.g. `emerald`, `sky`, `violet`), not amber.
8. **Risks / open questions** — anything a human should decide before building.

Keep it crisp: a human will skim, edit, and approve this — it is a plan, not an \
essay. Write ONLY `{PLAN_FILE}`. Do not scaffold code or create other files."""


def copy_template(dest: Path) -> None:
    """Copy the concept-template into a topic folder for building.

    Skips node_modules / build output; leaves PLAN.md in place.
    """
    if not TEMPLATE_DIR.exists():
        return
    ignore = shutil.ignore_patterns("node_modules", "dist", ".git", "*.log")
    for item in TEMPLATE_DIR.iterdir():
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True, ignore=ignore)
        else:
            shutil.copy2(item, target)


def build_prompt() -> str:
    """Instruction for turning an approved PLAN.md into a working repo.

    The concept-template has already been copied into the working directory,
    so the house style / boilerplate rules are condensed here rather than read
    from the meta-agent folder.
    """
    return f"""The concept-template (Vite + React 19 + TS + Tailwind 4 + \
framer-motion) has been copied into your current working directory, alongside an \
approved `{PLAN_FILE}`. Build the learning app described by PLAN.md by filling in \
the template — do not rebuild boilerplate.

Rules:
- Read PLAN.md first; it is the source of truth for repo name, sections, game \
mechanic, sub-concept keys, example levels, and accent color.
- Only edit files marked `TOPIC:` plus new files under `src/components/` and \
`src/game/`. Never restyle the shared primitives; the only global change is \
swapping the accent color family everywhere the template uses `amber-*`.
- LEARN (`src/pages/Learn.tsx` + `src/components/`): 4-6 numbered sections, each \
with an interactive visualization (one self-contained component per file, no \
required props, framer-motion transitions) or a worked example. Tight second-person prose.
- TEST (`src/pages/Test.tsx` + `src/game/`): 10-20 levels in `levels.ts` as pure \
data, easy -> hard, each tagged with a sub-concept key. Keep validation a pure \
function in `checkAnswer.ts` (no React imports); wrong answers return a teaching \
reason. Reuse `usePuzzle.ts` for type-the-answer games; write a sibling hook for a \
different mechanic.
- Update `index.html` title + favicon glyph, `package.json` name, and write a \
README (H1 = repo name, tab map with the game's *italic* name, ASCII layout tree, \
quick start, notes).
- Do NOT add dependencies beyond package.json. Never push, commit, or touch git.

Verify before finishing (fix and re-run until both are clean):
```
npm install
npm run lint
npm run build
```
Also smoke-test the game core: feed level 1's canonical answer through the \
validator and confirm it returns ok. Report what you built and the gate results."""


def improve_prompt(request: str) -> str:
    return (
        "The app in your current working directory is already built and working "
        "(a Vite + React + TypeScript learning app with a Learn page and a Test "
        "game). Apply this improvement without breaking what's there — change only "
        f"what's needed:\n\n{request}\n\nThen verify it still compiles cleanly:\n"
        "```\nnpm run lint\nnpm run build\n```\nFix and re-run until green, then "
        "briefly report what you changed. Do not touch git."
    )


# --- Git history ------------------------------------------------------------
# Every Grok change to an app is captured as a descriptive commit so a
# bad change can be rolled back. Commits are made by the backend (deterministic),
# not the agent — the house rules forbid the agent from touching git.
def _git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def _git_ensure_repo(cwd: Path) -> None:
    if (cwd / ".git").exists():
        return
    _git(["init", "-q"], cwd)
    _git(["config", "user.email", "factory@concept.local"], cwd)
    _git(["config", "user.name", "Concept Factory"], cwd)
    # Keep generated/heavy dirs out of history so commits are just source.
    gi = cwd / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    for pat in ("node_modules", "dist", ".cflogs"):
        if pat not in lines:
            lines.append(pat)
    gi.write_text("\n".join(lines) + "\n")


def seed_history(dest: Path, src: Optional[Path]) -> None:
    """Adopt a concept's real git history into its working copy.

    The workspace/runtime copies were made without .git, so review/revert
    would otherwise operate on a phantom timeline. This copies the source
    repo's .git in ONCE, then never touches it again.

    Invariant: if ``dest`` already has history, do nothing — we never replace
    or rewrite an existing timeline (that was the old overwriting bug). A
    missing or history-less ``src`` is tolerated: the concept simply starts
    its history at the first backend commit.
    """
    if (dest / ".git").exists():
        return  # already has a timeline — never overwrite it
    if not src or not (src / ".git").exists():
        return  # nothing to adopt; git_commit will init on first snapshot
    shutil.copytree(src / ".git", dest / ".git")
    # The copied index reflects src's tree, not dest's files. A mixed reset
    # realigns HEAD/index/worktree without discarding any local changes.
    _git(["reset", "--mixed", "-q", "HEAD"], dest)


def dist_base_ok(slug: str) -> bool:
    """True if the built bundle references the /concepts/<slug>/ asset base.

    A bundle built with Vite's default base ('/') will 404 its assets when
    served from the sub-path, so a False here is the signal that the bundle
    needs re-finalizing.
    """
    index = WORKSPACE / slug / "dist" / "index.html"
    if not index.is_file():
        return False
    return f"/concepts/{slug}/assets" in index.read_text()


def git_commit(cwd: Path, message: str) -> bool:
    """Snapshot the app's source as a commit (inits the repo on first use).

    Returns True if a commit was made, False if nothing changed.
    """
    _git_ensure_repo(cwd)
    _git(["add", "-A"], cwd)
    # dist/ is gitignored (it's generated), but we deliberately version the built
    # bundle too so any past version can be re-served by a plain git restore — no
    # Grok, no npm rebuild needed to switch versions.
    if (cwd / "dist").exists():
        _git(["add", "-f", "dist"], cwd)
    if _git(["diff", "--cached", "--quiet"], cwd).returncode == 0:
        return False  # nothing staged
    _git(["commit", "-q", "-m", message], cwd)
    return True


def has_committed_dist(cwd: Path, ref: str) -> bool:
    """True if commit ``ref`` carries a built bundle, i.e. it can be served by a
    plain git restore without rebuilding."""
    if not (cwd / ".git").exists():
        return False
    return _git(["cat-file", "-e", f"{ref}:dist/index.html"], cwd).returncode == 0


def served_hash(cwd: Path) -> str:
    """Full hash of the commit whose version is currently being served.

    Usually that's HEAD, but a revert records a synthetic ``Revert to <short>``
    commit at the tip whose content is really an earlier version — and those
    synthetic commits are hidden from the history — so resolve through it to the
    real commit the user is actually looking at.
    """
    if not (cwd / ".git").exists():
        return ""
    head = _git(["rev-parse", "HEAD"], cwd).stdout.strip()
    if not head:
        return ""
    subject = _git(["log", "-1", "--pretty=format:%s", "HEAD"], cwd).stdout.strip()
    m = re.match(r"^Revert to ([0-9a-f]{4,40})$", subject)
    if m:
        resolved = _git(
            ["rev-parse", "--verify", "--quiet", m.group(1) + "^{commit}"], cwd
        ).stdout.strip()
        if resolved:
            return resolved
    return head


# Auto-generated maintenance commits (reverts, protective snapshots) that the
# system creates for bookkeeping — not real user-facing changes, so they're
# hidden from the Versions history.
_INTERNAL_COMMIT_PREFIXES = ("Revert to ", "Snapshot before ")


def git_log(cwd: Path, n: int = 100) -> list:
    if not (cwd / ".git").exists():
        return []
    out = _git(["log", f"-{n}", "--pretty=format:%H%x1f%s%x1f%cI"], cwd).stdout
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        message = parts[1]
        if message.startswith(_INTERNAL_COMMIT_PREFIXES):
            continue
        commits.append({"hash": parts[0], "message": message, "date": parts[2]})
    return commits


def git_revert_to(cwd: Path, target: str) -> bool:
    """Restore the source to a prior commit as a NEW commit (history preserved
    so you can still go forward again)."""
    if not (cwd / ".git").exists():
        return False
    old = _git(["rev-parse", "HEAD"], cwd).stdout.strip()
    if not old or target == old:
        return False
    _git(["reset", "--hard", target], cwd)   # worktree + index -> target
    _git(["reset", "--soft", old], cwd)       # move HEAD back to tip, keep content
    if _git(["diff", "--cached", "--quiet"], cwd).returncode != 0:
        _git(["commit", "-q", "-m", f"Revert to {target[:8]}"], cwd)
    return True


def refine_prompt(feedback: str) -> str:
    return (
        "Revise PLAN.md based on this feedback. Keep the same section structure "
        "and rewrite the file in place — PLAN.md remains your only deliverable. "
        f"Feedback:\n\n{feedback}"
    )


def plan_title(plan_text: str) -> Optional[str]:
    """Pull a display title from a PLAN.md's first H1 (`# Foo — Plan` → `Foo`)."""
    for line in plan_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            title = re.sub(r"\s*[—–-]\s*Plan\s*$", "", title).strip()
            return title or None
    return None


def consolidate_prompt(plans: List[tuple], meta_prompt: str) -> str:
    """Synthesize several ready plans into ONE unified learning-app plan.

    ``plans`` is a list of (title, plan_markdown) for the selected topics.
    """
    meta = (
        f"\nBOARD INTENT (meta prompt steering the whole set): {meta_prompt.strip()}"
        if meta_prompt.strip()
        else ""
    )
    n = len(plans)
    blocks = "\n\n".join(
        f"===== SOURCE PLAN {i} — {title} =====\n{(plan or '').strip()}"
        for i, (title, plan) in enumerate(plans, 1)
    )
    return f"""You are CONSOLIDATING {n} separate single-concept learning micro-app \
plans into ONE unified plan. Each source below is a plan for its own tiny \
Vite + React + TypeScript + Tailwind learning app (a LEARN pocket-guide tab and a \
TEST game tab). Your job is to design a SINGLE app that teaches and tests ALL of \
these topics together as one coherent concept — not a menu of separate apps bolted \
together. Do NOT write app code. Your only deliverable is `{PLAN_FILE}` in your \
current working directory.{meta}

{blocks}

SYNTHESIZE, don't concatenate:
- Find the through-line that connects these topics and lead with it — the unified \
"aha" that makes learning them together stronger than learning them apart.
- Merge overlapping sub-concepts; keep every distinct one. Nothing important from \
any source plan should be dropped.
- Fold the source TEST games into ONE game whose levels span all the topics, each \
level still tagged with exactly one sub-concept key (reuse/rename the source keys \
so results break down by category across the merged set).
- Pick ONE accent Tailwind color family for the unified app.
- Keep it about the length of a SINGLE source plan — slightly longer is fine to \
cover the extra ground, but it must stay a crisp, skimmable plan, not the sum of \
all inputs. Tighten aggressively.

`{PLAN_FILE}` MUST be markdown with exactly these sections (same house pattern as a \
single-topic plan):
1. `# <Unified Title> — Plan`
2. **Repo name** — kebab-case, 1-3 words, concrete.
3. **One-line description** — the GitHub-style tagline for the combined app.
4. **Learning angle** — 2-3 sentences: the unifying mental model and why teaching \
these together sticks.
5. **Learn page** — 4-6 numbered section titles covering the merged material, each \
with a one-line note on its interactive visualization or worked example.
6. **Test game** — an *italicized name*, a one-paragraph mechanic pitch, why that \
mechanic fits the combined concept, the full list of sub-concept keys the levels \
cover (spanning all sources), and 3 example levels each written as: prompt -> \
expected answer -> teaching reason for a plausible wrong answer.
7. **Accent color** — one Tailwind family (not amber).
8. **Risks / open questions** — anything a human should decide before building, \
including any source material that was hard to unify.

Write ONLY `{PLAN_FILE}`. Do not scaffold code or create other files."""


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


def build_claude_cmd(
    prompt: str,
    cwd: Path,
    *,
    session_id: Optional[str] = None,
    dangerously_skip: bool = False,
    permission_mode: str = "bypassPermissions",
    model: str = "",
    effort: str = "",
    bin_path: Optional[str] = None,
) -> List[str]:
    """Build the argv for a headless Claude Code turn.

    Claude's print mode uses ``-p`` / ``--print`` with ``stream-json`` output.
    ``--verbose`` is required so intermediate assistant events stream live
    rather than only the final result.
    """
    cmd = [
        bin_path or CLAUDE_BIN,
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    # cwd is the process working directory; also pass --add-dir for tool access.
    skip = bool(dangerously_skip)
    if skip:
        cmd += ["--dangerously-skip-permissions"]
    elif permission_mode:
        cmd += ["--permission-mode", permission_mode]
    if model and str(model).strip():
        cmd += ["--model", str(model).strip()]
    if effort and str(effort).strip():
        cmd += ["--effort", str(effort).strip()]
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


def _run_claude_once(
    prompt: str,
    cwd: Path,
    emit: Callable[[str], None],
    session_id: Optional[str],
    dangerously_skip: bool,
    permission_mode: str,
    timeout: int,
    model: str = "",
    effort: str = "",
    recorder=None,
) -> dict:
    """Single attempt at a headless Claude Code turn."""
    cmd = build_claude_cmd(
        prompt,
        cwd,
        session_id=session_id,
        dangerously_skip=dangerously_skip,
        permission_mode=permission_mode,
        model=model,
        effort=effort,
    )
    return _run_cli_once(
        cmd,
        cwd,
        emit,
        session_id,
        timeout,
        driver_label="Claude",
        stream_kind="claude",
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


def run_claude(
    prompt: str,
    cwd: Path,
    on_line: Optional[Callable[[str], None]] = None,
    session_id: Optional[str] = None,
    permission_mode: str = "bypassPermissions",
    dangerously_skip: bool = False,
    timeout: int = PLAN_TIMEOUT,
    model: str = "",
    effort: str = "",
    recorder=None,
) -> dict:
    """Run one headless Claude Code turn, streaming progress via ``on_line``.

    Uses ``--output-format stream-json --verbose``. Returns ``{sessionId, error}``.
    Auth is Claude's own (OAuth or ``ANTHROPIC_API_KEY``).
    """
    emit = on_line or (lambda _s: None)
    result = _run_claude_once(
        prompt,
        cwd,
        emit,
        session_id,
        dangerously_skip,
        permission_mode,
        timeout,
        model=model,
        effort=effort,
        recorder=recorder,
    )
    if result["error"] and session_id and _looks_like_session_error(result["error"]):
        emit("Session resume failed — starting a fresh Claude session…")
        if recorder is not None:
            recorder.retry()
        result = _run_claude_once(
            prompt,
            cwd,
            emit,
            None,
            dangerously_skip,
            permission_mode,
            timeout,
            model=model,
            effort=effort,
            recorder=recorder,
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


# --- Serving the built concept ----------------------------------------------
def patch_router_basename(cwd: Path) -> None:
    """Give BrowserRouter a basename so the built app works under a sub-path.

    The template uses absolute routes (/learn, /test) with a plain
    <BrowserRouter>; served from /concepts/<slug>/ that breaks unless the
    router knows its base. import.meta.env.BASE_URL matches the Vite --base.
    """
    main = cwd / "src" / "main.tsx"
    if not main.exists():
        return
    txt = main.read_text()
    if "basename=" in txt:
        return
    patched = txt.replace(
        "<BrowserRouter>",
        "<BrowserRouter basename={import.meta.env.BASE_URL}>",
    )
    if patched != txt:
        main.write_text(patched)


def finalize_build(cwd: Path, base: str, on_line: Callable[[str], None]) -> bool:
    """Produce a sub-path-correct production build we can serve from FastAPI."""
    patch_router_basename(cwd)
    if not (cwd / "node_modules").exists():
        on_line("$ npm install")
        subprocess.run(
            ["npm", "install"], cwd=str(cwd), capture_output=True, text=True, timeout=900
        )
    on_line(f"$ npm run build -- --base={base}")
    proc = subprocess.run(
        ["npm", "run", "build", "--", f"--base={base}"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=900,
    )
    ok = proc.returncode == 0 and (cwd / "dist" / "index.html").exists()
    if ok:
        on_line("✓ production build ready to serve")
    else:
        on_line((proc.stderr or proc.stdout or "build failed").strip()[-400:])
    return ok


# --- Verification gates (harness-run, never trusted to the agent) ------------
GATE_TIMEOUT = 300

# Auto-plays every game level: bundles the concept's own levels.ts +
# checkAnswer.ts with the esbuild already inside its node_modules (vite dep —
# no extra install), then feeds each level's canonical answer through the
# validator. Emits ONE JSON line on stdout.
_VALIDATOR_JS = r"""
const path = require('path');
(async () => {
  const cwd = process.cwd();
  let esbuild;
  try {
    esbuild = require(path.join(cwd, 'node_modules', 'esbuild'));
  } catch (e) {
    console.log(JSON.stringify({ status: 'skipped', detail: 'esbuild not installed (npm install first)' }));
    return;
  }
  const entry = [
    "import { LEVELS } from './src/game/levels'",
    "import { checkAnswer } from './src/game/checkAnswer'",
    "export { LEVELS, checkAnswer }",
  ].join('\n');
  const built = await esbuild.build({
    stdin: { contents: entry, resolveDir: cwd, sourcefile: 'cf-validate-entry.ts', loader: 'ts' },
    bundle: true,
    format: 'cjs',
    platform: 'node',
    write: false,
    logLevel: 'silent',
    external: ['react', 'react-dom', 'react-router-dom', 'framer-motion'],
  });
  const mod = { exports: {} };
  new Function('module', 'exports', 'require', built.outputFiles[0].text)(mod, mod.exports, require);
  const LEVELS = mod.exports.LEVELS;
  const checkAnswer = mod.exports.checkAnswer;
  if (!Array.isArray(LEVELS) || typeof checkAnswer !== 'function') {
    console.log(JSON.stringify({ status: 'error', detail: 'LEVELS array or checkAnswer() not exported from src/game' }));
    return;
  }
  const levels = [];
  for (const level of LEVELS) {
    let ok = false;
    let reason = '';
    try {
      const answer = typeof level.answer === 'string' ? level.answer : JSON.stringify(level.answer);
      const res = checkAnswer(answer, level);
      ok = !!(res && res.ok);
      reason = ok ? '' : String((res && res.reason) || 'canonical answer rejected');
    } catch (e) {
      reason = 'validator threw: ' + String((e && e.message) || e);
    }
    levels.push({ id: level.id, topic: level.topic || '', ok, reason: reason.slice(0, 300) });
  }
  const passed = levels.filter((l) => l.ok).length;
  console.log(JSON.stringify({
    status: passed === levels.length && levels.length > 0 ? 'pass' : 'fail',
    passed,
    total: levels.length,
    levels,
  }));
})().catch((e) => {
  console.log(JSON.stringify({ status: 'error', detail: String((e && e.message) || e).slice(0, 400) }));
});
"""


def run_lint_gate(cwd: Path, on_line: Callable[[str], None]) -> dict:
    """Harness-run ``npm run lint`` gate → {status: pass|fail|skipped, detail}."""
    pkg = cwd / "package.json"
    try:
        scripts = (json.loads(pkg.read_text()).get("scripts") or {}) if pkg.is_file() else {}
    except (json.JSONDecodeError, ValueError, OSError):
        scripts = {}
    if "lint" not in scripts:
        return {"status": "skipped", "detail": "no lint script in package.json"}
    on_line("$ npm run lint")
    try:
        proc = subprocess.run(
            ["npm", "run", "lint"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GATE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        on_line("⚠ lint timed out")
        return {"status": "fail", "detail": f"lint timed out after {GATE_TIMEOUT}s"}
    if proc.returncode == 0:
        on_line("✓ lint clean")
        return {"status": "pass", "detail": ""}
    detail = (proc.stdout or proc.stderr or "lint failed").strip()[-800:]
    on_line("✗ lint failed")
    return {"status": "fail", "detail": detail}


def run_validator_gate(cwd: Path, on_line: Callable[[str], None]) -> dict:
    """Auto-play every game level through the concept's own pure validator.

    Returns {status, passed, total, passRate, levels: [{id, topic, ok, reason}]}
    — the per-category pass rate the dashboard charts. ``skipped`` when the
    concept has no standard game module (e.g. plan-only or full-stack apps).
    """
    if not (cwd / "src" / "game" / "levels.ts").is_file():
        return {"status": "skipped", "detail": "no src/game/levels.ts"}
    script_dir = cwd / ".cflogs"
    script_dir.mkdir(exist_ok=True)
    script = script_dir / "validate.cjs"
    try:
        script.write_text(_VALIDATOR_JS)
    except OSError as e:
        return {"status": "error", "detail": f"could not write validator: {e}"}
    on_line("Auto-playing game levels through the validator…")
    try:
        proc = subprocess.run(
            ["node", str(script)],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GATE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        on_line("⚠ validator timed out")
        return {"status": "error", "detail": f"validator timed out after {GATE_TIMEOUT}s"}
    except FileNotFoundError:
        return {"status": "skipped", "detail": "node not found on PATH"}
    result = None
    for line in reversed((proc.stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                result = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if not isinstance(result, dict):
        detail = (proc.stderr or proc.stdout or "no validator output").strip()[-800:]
        on_line("⚠ validator produced no result")
        return {"status": "error", "detail": detail}
    total = int(result.get("total") or 0)
    passed = int(result.get("passed") or 0)
    if total:
        result["passRate"] = round(passed / total, 4)
        on_line(
            f"{'✓' if result.get('status') == 'pass' else '✗'} validator: "
            f"{passed}/{total} levels pass"
        )
    else:
        on_line(f"⚠ validator: {result.get('detail') or result.get('status')}")
    return result


# --- Live topic chat + credit balance (xAI HTTP API) -------------------------
# Chat Q&A uses the chat-completions API (no tools) so answers stream fast and
# never mutate the app. Improve/build still go through headless `grok`.
#
# Credits HUD reads the SAME prepaid balance as console.x.ai via the
# Management API:
#   GET https://management-api.x.ai/v1/billing/teams/{team_id}/prepaid/balance
# That endpoint requires an xAI *management key* (not the inference API key).
# Create one at: console.x.ai → Settings → Management Keys
#   export XAI_MANAGEMENT_API_KEY=...

import ssl
import time
import urllib.error
import urllib.request

XAI_API_BASE = os.environ.get("XAI_API_BASE", "https://api.x.ai/v1").rstrip("/")
XAI_MGMT_BASE = os.environ.get(
    "XAI_MANAGEMENT_API_BASE", "https://management-api.x.ai"
).rstrip("/")
CHAT_MODEL = os.environ.get("CF_CHAT_MODEL", "grok-3-mini")
# xAI reports cost_in_usd_ticks on inference; 1e9 ticks ≈ $1.00.
USD_TICKS_PER_DOLLAR = 1_000_000_000

_balance_lock = threading.Lock()
_rate_limit: dict = {}
_session_spend_usd = 0.0
_session_tokens = 0
# Cache of the console prepaid balance so the HUD can poll without hammering.
_console_balance: dict = {"ts": 0.0, "data": None, "error": None}
_CONSOLE_BALANCE_TTL = 30.0  # seconds
# Session spend ledger only (not the source of truth for remaining credits).
USAGE_FILE = Path(__file__).parent / "usage.json"


def _xai_key() -> Optional[str]:
    return os.environ.get("XAI_API_KEY") or None


def _mgmt_key() -> Optional[str]:
    """Management key for billing (console.x.ai prepaid balance)."""
    return (
        os.environ.get("XAI_MANAGEMENT_API_KEY")
        or os.environ.get("XAI_MANAGEMENT_KEY")
        or None
    )


def _ssl_context() -> ssl.SSLContext:
    """Prefer certifi's CA bundle (macOS system Python often lacks one)."""
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def ticks_to_usd(ticks: int) -> float:
    return float(ticks) / USD_TICKS_PER_DOLLAR


def _load_usage() -> dict:
    """Local session/lifetime spend ledger — NOT console remaining balance."""
    if not USAGE_FILE.is_file():
        return {}
    try:
        data = json.loads(USAGE_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_usage(data: dict) -> None:
    try:
        USAGE_FILE.write_text(json.dumps(data, indent=2) + "\n")
    except Exception:
        pass


def set_budget_usd(amount: Optional[float]) -> dict:
    """No-op kept for API compat — real balance comes from console.x.ai."""
    del amount
    return get_balance(force=True)


def _cents_obj_to_usd(obj) -> Optional[float]:
    """xAI represents money as {\"val\": \"<cents>\"} (sign-convention: credit is negative).

    Console remaining credits = -val / 100. Example: val \"-298\" → $2.98 left.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        raw = obj.get("val")
    else:
        raw = obj
    if raw is None or raw == "":
        return None
    try:
        cents = int(str(raw))
    except (TypeError, ValueError):
        try:
            cents = int(float(str(raw)))
        except (TypeError, ValueError):
            return None
    # Prepaid credit balances are stored as negative cents on the wire.
    return round((-cents) / 100.0, 4)


def _http_json(
    url: str,
    *,
    key: str,
    method: str = "GET",
    body: Optional[dict] = None,
    timeout: int = 20,
) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        raw = resp.read()
    if not raw:
        return {}
    return json.loads(raw.decode())


def _resolve_team_id() -> Optional[str]:
    """Team ID for billing — env override or /v1/me via inference API key."""
    env = (os.environ.get("XAI_TEAM_ID") or "").strip()
    if env:
        return env
    key = _xai_key()
    if not key:
        return None
    try:
        me = _http_json(f"{XAI_API_BASE}/me", key=key, timeout=15)
        return me.get("team_id") or (me.get("api_key") or {}).get("team_id")
    except Exception:
        try:
            ak = _http_json(f"{XAI_API_BASE}/api-key", key=key, timeout=15)
            return ak.get("team_id")
        except Exception:
            return None


def _money_cents(obj) -> Optional[int]:
    """Extract integer cents from an xAI money object ``{\"val\": \"…\"}``."""
    if obj is None:
        return None
    raw = obj.get("val") if isinstance(obj, dict) else obj
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        try:
            return int(float(str(raw)))
        except (TypeError, ValueError):
            return None


def _fetch_console_prepaid(team_id: str, mgmt_key: str) -> dict:
    """Live prepaid remaining from the same Management API console.x.ai uses.

    Important: ``GET …/prepaid/balance`` ``total`` is *lifetime top-ups*
    (sum of PURCHASE/AUTO_PURCHASE), NOT remaining. Remaining is:

        prepaidCredits − prepaidCreditsUsed   (invoice preview)

    Wire amounts use credit-negative cents (e.g. -3000 → $30.00 credit).
    """
    # Lifetime purchased (for "of $X" detail) — optional, best-effort.
    purchased = None
    try:
        bal = _http_json(
            f"{XAI_MGMT_BASE}/v1/billing/teams/{team_id}/prepaid/balance",
            key=mgmt_key,
            timeout=20,
        )
        purchased = _cents_obj_to_usd(bal.get("total"))
    except Exception:
        bal = None

    # Remaining comes from the current-cycle invoice preview fields that
    # console.x.ai itself surfaces on the billing page.
    prev = _http_json(
        f"{XAI_MGMT_BASE}/v1/billing/teams/{team_id}/postpaid/invoice/preview",
        key=mgmt_key,
        timeout=20,
    )
    core = prev.get("coreInvoice") or {}
    issued_cents = _money_cents(core.get("prepaidCredits"))
    used_cents = _money_cents(core.get("prepaidCreditsUsed"))

    issued = _cents_obj_to_usd(core.get("prepaidCredits"))
    if issued is None:
        issued = purchased

    # Both fields are credit-negative on the wire. Absolute dollars used:
    used = None
    if used_cents is not None:
        used = round(abs(used_cents) / 100.0, 4)

    remaining = None
    if issued_cents is not None and used_cents is not None:
        # Credit remaining in wire cents, then convert with the same rule.
        # e.g. issued=-3000, used=-2537 → remaining_cents=-463 → $4.63
        remaining = _cents_obj_to_usd({"val": str(issued_cents - used_cents)})
    elif issued is not None and used is not None:
        remaining = round(issued - used, 4)
    elif issued is not None:
        remaining = issued

    if remaining is None:
        raise RuntimeError(
            f"could not derive prepaid remaining from invoice preview: "
            f"prepaidCredits={core.get('prepaidCredits')!r} "
            f"prepaidCreditsUsed={core.get('prepaidCreditsUsed')!r}"
        )[:240]

    return {
        "remainingUsd": remaining,
        "prepaidIssuedUsd": issued,
        "prepaidUsedUsd": used,
        "teamId": team_id,
        "rawTotal": (bal or {}).get("total") if isinstance(bal, dict) else None,
        "source": "console.x.ai/management-api",
    }


def topic_context(slug: str, title: str = "", blurb: str = "") -> str:
    """Gather PLAN.md / README so the tutor knows what this concept teaches."""
    d = WORKSPACE / slug
    chunks: List[str] = []
    if title:
        chunks.append(f"TOPIC TITLE: {title}")
    if blurb:
        chunks.append(f"BLURB: {blurb}")
    for name in (PLAN_FILE, "README.md"):
        path = d / name
        if path.is_file():
            text = path.read_text(errors="replace").strip()
            if text:
                # Cap each file so the system prompt stays lean.
                chunks.append(f"===== {name} =====\n{text[:7000]}")
    return "\n\n".join(chunks) if chunks else f"TOPIC: {title or slug}"


def chat_system_prompt(context: str) -> str:
    return f"""You are a live tutor embedded in a single-concept CS learning micro-app \
(Learn pocket-guide + Test game). The student is on the concept page right now.

Your job: answer questions about THIS topic, clarify confusing bits, give \
hints on the Test game when stuck (prefer progressive hints over spoilers — \
only give the full answer if they explicitly ask), and connect ideas to what \
the app actually teaches.

Rules:
- Ground every answer in the plan/README context below. If something isn't \
covered, say so and reason carefully from first principles.
- Be concise and second-person. Prefer short paragraphs, examples, and \
worked steps over essays.
- Do NOT rewrite, redesign, or invent app code. This is Q&A, not an editor \
(there's a separate Improve tab for that).
- If they ask something off-topic, briefly redirect to the concept.

CONTEXT FOR THIS CONCEPT:
{context}"""


def _record_balance_from_headers(headers) -> None:
    """Cache rate-limit headroom (throughput) from an xAI response."""

    def _int(name: str) -> Optional[int]:
        raw = headers.get(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    rem_tok = _int("x-ratelimit-remaining-tokens")
    lim_tok = _int("x-ratelimit-limit-tokens")
    rem_req = _int("x-ratelimit-remaining-requests")
    lim_req = _int("x-ratelimit-limit-requests")
    if rem_tok is None and rem_req is None:
        return
    with _balance_lock:
        _rate_limit.update(
            {
                "remainingTokens": rem_tok,
                "limitTokens": lim_tok,
                "remainingRequests": rem_req,
                "limitRequests": lim_req,
                "updatedAt": time.time(),
            }
        )


def _bump_session_spend(usage: Optional[dict]) -> None:
    """Record dollar cost from an xAI ``usage`` block (persisted)."""
    if not usage:
        return
    ticks = usage.get("cost_in_usd_ticks") or 0
    tokens = usage.get("total_tokens") or 0
    usd = ticks_to_usd(int(ticks)) if ticks else 0.0
    if usd <= 0 and not tokens:
        return
    global _session_spend_usd, _session_tokens
    with _balance_lock:
        _session_spend_usd = round(_session_spend_usd + usd, 6)
        _session_tokens += int(tokens)
        u = _load_usage()
        u["spentUsd"] = round(float(u.get("spentUsd") or 0) + usd, 6)
        u["totalTokens"] = int(u.get("totalTokens") or 0) + int(tokens)
        u["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _save_usage(u)


def _fmt_usd(n: float, digits: int = 2) -> str:
    """Format dollars; use more precision for tiny session spends."""
    n = float(n)
    if digits == 2 and 0 < abs(n) < 0.01:
        return f"${n:.4f}"
    return f"${n:,.{digits}f}"


def _fmt_count(n: int) -> str:
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.1f}k".replace(".0k", "k")
    return str(n)


def _get_console_prepaid(force: bool = False) -> dict:
    """Fetch (or return cached) prepaid balance from management-api.x.ai.

    This is the same prepaid remaining figure shown on console.x.ai.
    Requires ``XAI_MANAGEMENT_API_KEY`` (inference API keys return 401).
    """
    now = time.time()
    with _balance_lock:
        cached = _console_balance.get("data")
        cached_err = _console_balance.get("error")
        ts = float(_console_balance.get("ts") or 0)
        if not force and (now - ts) < _CONSOLE_BALANCE_TTL and (cached or cached_err):
            if cached is not None:
                return {"ok": True, **cached}
            return {"ok": False, "error": cached_err or "unknown"}

    mgmt = _mgmt_key()
    if not mgmt:
        err = (
            "Set XAI_MANAGEMENT_API_KEY (console.x.ai → Settings → Management Keys). "
            "Inference XAI_API_KEY cannot read billing."
        )
        with _balance_lock:
            _console_balance.update({"ts": now, "data": None, "error": err})
        return {"ok": False, "error": err}

    team_id = _resolve_team_id()
    if not team_id:
        err = "Could not resolve team id (set XAI_TEAM_ID or XAI_API_KEY)"
        with _balance_lock:
            _console_balance.update({"ts": now, "data": None, "error": err})
        return {"ok": False, "error": err}

    try:
        data = _fetch_console_prepaid(team_id, mgmt)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:240]
        except Exception:
            pass
        if e.code == 401:
            err = (
                "Management key rejected (401). Create a Management Key at "
                "console.x.ai → Settings → Management Keys and export "
                "XAI_MANAGEMENT_API_KEY."
            )
        else:
            err = f"Management API HTTP {e.code}: {body or e.reason}"
        with _balance_lock:
            _console_balance.update({"ts": now, "data": None, "error": err})
        return {"ok": False, "error": err}
    except Exception as e:
        err = f"Management API error: {e}"
        with _balance_lock:
            _console_balance.update({"ts": now, "data": None, "error": err})
        return {"ok": False, "error": err}

    with _balance_lock:
        _console_balance.update({"ts": now, "data": data, "error": None})
    return {"ok": True, **data}


def get_balance(force: bool = False) -> dict:
    """Live prepaid $ remaining from console.x.ai (Management API).

    Primary source: GET management-api.x.ai/.../prepaid/balance
    (same figure as the Credits page on console.x.ai).

    Local usage.json is only used for optional session-spend detail — never
    as the remaining balance. Rate-limit tokens are headroom only.
    """
    with _balance_lock:
        usage = _load_usage()
        spent = float(usage.get("spentUsd") or 0)
        session = _session_spend_usd
        session_tok = _session_tokens
        rl = dict(_rate_limit)

    console = _get_console_prepaid(force=force)

    if not console.get("ok"):
        err = console.get("error") or "console balance unavailable"
        return {
            "ok": False,
            "currency": "USD",
            "source": "console.x.ai",
            "label": "Credits unavailable",
            "detail": err,
            "error": err,
            "spentUsd": round(spent, 6),
            "sessionSpendUsd": round(session, 6),
            "sessionTokens": session_tok,
            "budgetUsd": None,
            "remainingUsd": None,
            "prepaidIssuedUsd": None,
            "prepaidUsedUsd": None,
            "pct": None,
            "remainingTokens": rl.get("remainingTokens"),
            "limitTokens": rl.get("limitTokens"),
            "remainingRequests": rl.get("remainingRequests"),
            "limitRequests": rl.get("limitRequests"),
        }

    remaining = console.get("remainingUsd")
    issued = console.get("prepaidIssuedUsd")
    used = console.get("prepaidUsedUsd")
    if used is None and issued is not None and remaining is not None:
        used = round(max(0.0, issued - remaining), 4)

    pct = None
    if issued and issued > 0 and remaining is not None:
        pct = round(100.0 * max(0.0, remaining) / issued, 1)

    if remaining is not None:
        label = f"{_fmt_usd(max(0.0, remaining))} left"
        if remaining < 0:
            label = f"{_fmt_usd(abs(remaining))} overdrawn"
    else:
        label = "Credits"

    bits: List[str] = ["console.x.ai"]
    if used is not None and issued is not None:
        bits.append(f"{_fmt_usd(used)} of {_fmt_usd(issued)} used")
    elif used is not None:
        bits.append(f"{_fmt_usd(used)} used")
    if session > 0:
        bits.append(f"session {_fmt_usd(session)}")
    if rl.get("remainingTokens") is not None and rl.get("limitTokens"):
        bits.append(
            f"headroom {_fmt_count(rl['remainingTokens'])}/{_fmt_count(rl['limitTokens'])} tok"
        )
    elif rl.get("remainingRequests") is not None and rl.get("limitRequests"):
        bits.append(
            f"headroom {_fmt_count(rl['remainingRequests'])}/{_fmt_count(rl['limitRequests'])} req"
        )

    return {
        "ok": True,
        "currency": "USD",
        "source": console.get("source") or "console.x.ai/management-api",
        "label": label,
        "detail": " · ".join(bits),
        "spentUsd": round(float(used if used is not None else spent), 6),
        "sessionSpendUsd": round(session, 6),
        "sessionTokens": session_tok,
        "budgetUsd": issued,  # total prepaid issued (for bar / compat)
        "remainingUsd": remaining,
        "prepaidIssuedUsd": issued,
        "prepaidUsedUsd": used,
        "pct": pct,  # % of prepaid pack remaining
        "teamId": console.get("teamId"),
        "remainingTokens": rl.get("remainingTokens"),
        "limitTokens": rl.get("limitTokens"),
        "remainingRequests": rl.get("remainingRequests"),
        "limitRequests": rl.get("limitRequests"),
        "error": None,
    }


def stream_chat(
    messages: List[dict],
    on_delta: Optional[Callable[[str], None]] = None,
) -> dict:
    """Stream one tutor turn via xAI chat completions.

    ``messages`` is OpenAI-style [{role, content}, ...] including system.
    Yields text via ``on_delta``. Returns {text, error, usage}.
    """
    key = _xai_key()
    if not key:
        return {"text": "", "error": "XAI_API_KEY not set", "usage": None}

    body = json.dumps(
        {
            "model": CHAT_MODEL,
            "messages": messages,
            "stream": True,
            "temperature": 0.5,
        }
    ).encode()
    req = urllib.request.Request(
        f"{XAI_API_BASE}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    emit = on_delta or (lambda _s: None)
    parts: List[str] = []
    usage = None
    try:
        with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as resp:
            _record_balance_from_headers(resp.headers)
            while True:
                raw = resp.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    evt = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if evt.get("usage"):
                    usage = evt["usage"]
                for choice in evt.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content") or ""
                    if delta:
                        parts.append(delta)
                        emit(delta)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        return {"text": "".join(parts), "error": f"xAI {e.code}: {detail}", "usage": None}
    except Exception as e:  # noqa: BLE001
        return {"text": "".join(parts), "error": str(e), "usage": None}

    _bump_session_spend(usage)
    return {"text": "".join(parts), "error": None, "usage": usage}
