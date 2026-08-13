"""xAI HTTP API: tutor chat streaming, credits/usage tracking."""


from __future__ import annotations


import json


import os


import threading


from typing import Callable, List, Optional


import ssl


import time


import urllib.error


import urllib.request


from .paths import USAGE_FILE, WORKSPACE


from .workspace import PLAN_FILE


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
