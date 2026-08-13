"""Factory driver settings: persistence, normalization, budgets."""


from __future__ import annotations


import json


import math


import os


import shutil


import threading


from typing import Any, Dict, Optional


from .paths import SETTINGS_FILE


# Sentinel: build job did not pass an explicit per-build budget override
# (fall back to settings.grok.maxBuildBudgetUsd). Distinct from None, which
# means "unlimited for this build".
_BUDGET_UNSET: Any = object()


# Path to the Grok CLI. Override with GROK_BIN if it isn't on PATH
# (common install: ~/.grok/bin/grok).
GROK_BIN = os.environ.get("GROK_BIN") or shutil.which("grok") or "grok"


_settings_lock = threading.Lock()


DRIVER_GROK = "grok"


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
