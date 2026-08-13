"""Live CLI settings-catalog discovery, TTL cache, and CLI write-back."""


from __future__ import annotations


import json


import os


import re


import shutil


import subprocess


import threading


from concurrent.futures import ThreadPoolExecutor


from pathlib import Path


from typing import Any, List, Optional


import time as _time


from .paths import _HELP_CACHE_FILE


from .settings import DRIVER_GROK, GROK_BIN, normalize_settings


# Wall-clock for a single discovery subprocess.
CATALOG_CLI_TIMEOUT = int(os.environ.get("CF_SETTINGS_CATALOG_TIMEOUT", "90"))


# How long a successful catalog poll is reused (seconds). Discovery is now
# file-first (~ms), so a short TTL is cheap and keeps the widget in step with
# changes made directly in the CLIs (e.g. /model in an interactive session).
CATALOG_TTL_SECONDS = int(os.environ.get("CF_SETTINGS_CATALOG_TTL", "15"))


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


def run_discovery_cli(
    argv: List[str],
    timeout: Optional[int] = None,
) -> dict:
    """Spawn a discovery CLI and return {argv, stdout, stderr, returncode, error}.

    This is the single spawn seam tests spy on to prove live polling vs cache hits.
    """
    global _cli_spawn_count
    _cli_spawn_count += 1
    t = CATALOG_CLI_TIMEOUT if timeout is None else timeout
    try:
        return _run_discovery_cli_pipes(argv, t)
    except FileNotFoundError as e:
        return {
            "argv": list(argv),
            "stdout": "",
            "stderr": "",
            "returncode": 127,
            "error": f"CLI not found: {e}",
        }
    except subprocess.TimeoutExpired as e:
        return {
            "argv": list(argv),
            "stdout": (e.stdout or "") if isinstance(e.stdout, str) else "",
            "stderr": (e.stderr or "") if isinstance(e.stderr, str) else "",
            "returncode": -1,
            "error": f"timed out after {t}s",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "argv": list(argv),
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "error": str(e),
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
    """``--effort`` levels parsed from CLI help text."""
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


_help_cache_lock = threading.Lock()


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


def resolve_model_selection(
    stored: str,
    cli_current: str,
    *,
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


def cli_sync_enabled() -> bool:
    v = os.environ.get("CF_SETTINGS_SYNC_CLI", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


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
