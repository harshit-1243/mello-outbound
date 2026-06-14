"""Free-credit / usage monitor for the AI providers (Cerebras LLM + Sarvam STT/TTS).

Neither Cerebras nor Sarvam exposes a reliable "remaining balance" API on the free tier, so this
infers the situation two ways:

1. **Quota-error detection (reliable):** when a provider call fails with an auth/quota/credit error
   (HTTP 401/402/403/429 or a "quota/credit/limit/exhausted" message), we record an ALERT. That is
   the actual "free credits are over" signal.
2. **Usage estimation (proactive gauge):** we tally per-day usage — LLM tokens, TTS characters,
   STT seconds — against the configured free-tier limits and warn as you approach them.

Counters are persisted to ``backend/usage/usage_<YYYY-MM-DD>.json`` so the voice-bot process (which
records usage) and the API process (which serves the dashboard) share the same state across
processes, and so usage survives a bot restart within the day. Cerebras' free tier resets daily, so
day-keyed files match the limit that matters.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
from pathlib import Path

from app.config import settings

USAGE_DIR = Path(__file__).resolve().parents[2] / "usage"
_LOCK = threading.Lock()

# Substrings / codes that mean "this provider rejected us for credit/quota/auth reasons".
_QUOTA_PATTERNS = re.compile(
    r"(429|401|402|403|quota|credit|insufficient|exhaust|too many requests|rate limit|"
    r"payment required|billing|out of (credits|quota))",
    re.IGNORECASE,
)


def _today() -> str:
    return dt.date.today().isoformat()


def _path(date: str | None = None) -> Path:
    return USAGE_DIR / f"usage_{date or _today()}.json"


def _blank() -> dict:
    return {"date": _today(), "llm_tokens": 0, "tts_chars": 0, "stt_seconds": 0.0, "alerts": []}


def _load(date: str | None = None) -> dict:
    p = _path(date)
    if not p.exists():
        return _blank()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _blank()


def _save(data: dict) -> None:
    try:
        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        _path(data.get("date")).write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass  # usage tracking must never break a live call


def _bump(field: str, amount) -> None:
    if not amount:
        return
    with _LOCK:
        data = _load()
        data[field] = (data.get(field) or 0) + amount
        _save(data)


def record_llm_tokens(n: int) -> None:
    _bump("llm_tokens", int(n or 0))


def record_tts_chars(n: int) -> None:
    _bump("tts_chars", int(n or 0))


def record_stt_seconds(seconds: float) -> None:
    _bump("stt_seconds", float(seconds or 0))


def record_alert(provider: str, message: str) -> None:
    """Record a credit/quota-exhausted event (the real 'free credits over' signal)."""
    with _LOCK:
        data = _load()
        data.setdefault("alerts", []).append(
            {"provider": provider, "message": str(message)[:300], "ts": dt.datetime.now().isoformat(timespec="seconds")}
        )
        _save(data)
    # Make it impossible to miss in the bot console.
    print(f"\n*** CREDIT ALERT [{provider}] *** {str(message)[:200]}\n", flush=True)


def looks_like_quota_error(text: str) -> bool:
    return bool(text and _QUOTA_PATTERNS.search(str(text)))


def maybe_record_quota_error(provider: str, text: str) -> bool:
    """If ``text`` looks like a credit/quota rejection, record an alert. Returns True if it did."""
    if looks_like_quota_error(text):
        record_alert(provider, text)
        return True
    return False


def _meter(key: str, label: str, unit: str, used, limit: int) -> dict:
    used = round(float(used or 0), 1) if isinstance(used, float) else int(used or 0)
    limit = int(limit or 0)
    if limit <= 0:
        status, pct = "unknown", None
    else:
        pct = round(100 * float(used) / limit, 1)
        status = "over" if pct >= 100 else ("warn" if pct >= settings.usage_warn_ratio * 100 else "ok")
    return {"key": key, "label": label, "unit": unit, "used": used, "limit": limit, "pct": pct, "status": status}


def snapshot() -> dict:
    """Per-meter usage vs configured free-tier limits + today's credit alerts. Read by /usage."""
    data = _load()
    meters = [
        _meter("llm", "Cerebras LLM", "tokens/day", data.get("llm_tokens"), settings.cerebras_daily_token_limit),
        _meter("tts", "Sarvam TTS", "chars/day", data.get("tts_chars"), settings.sarvam_daily_char_limit),
        _meter("stt", "Sarvam STT", "sec/day", data.get("stt_seconds"), settings.sarvam_daily_stt_seconds_limit),
    ]
    alerts = data.get("alerts", [])
    exhausted = bool(alerts) or any(m["status"] == "over" for m in meters)
    return {"date": data.get("date", _today()), "meters": meters, "alerts": alerts[-10:], "exhausted": exhausted}


# ---------------------------------------------------------------------------
# Pipecat observer: feed the monitor from the live pipeline.
# ---------------------------------------------------------------------------

def make_usage_observer():
    """A BaseObserver that records LLM token / TTS character usage from MetricsFrame and turns any
    quota-shaped ErrorFrame into a credit alert. Returns None if the observer API is unavailable."""
    try:
        from pipecat.observers.base_observer import BaseObserver
        from pipecat.frames.frames import ErrorFrame, MetricsFrame
    except Exception:  # noqa: BLE001 — older/newer pipecat without these symbols
        return None

    llm_provider = settings.llm_provider
    tts_provider = settings.tts_provider

    class UsageObserver(BaseObserver):
        async def on_push_frame(self, data):  # noqa: ANN001 — FramePushed
            frame = getattr(data, "frame", None)
            if frame is None:
                return
            if isinstance(frame, MetricsFrame):
                for item in getattr(frame, "data", []) or []:
                    # Duck-type across pipecat metric data classes (tokens / characters).
                    tokens = getattr(item, "total_tokens", None)
                    if tokens is None:
                        v = getattr(item, "value", None)
                        tokens = v if (v is not None and "token" in type(item).__name__.lower()) else None
                    if tokens:
                        record_llm_tokens(int(tokens))
                    chars = getattr(item, "characters", None) or getattr(item, "character_count", None)
                    if chars:
                        record_tts_chars(int(chars))
            elif isinstance(frame, ErrorFrame):
                msg = getattr(frame, "error", None) or str(frame)
                if looks_like_quota_error(msg):
                    # Attribute to the most likely culprit by message hints, else the LLM.
                    low = str(msg).lower()
                    provider = (
                        tts_provider if ("tts" in low or "speech" in low or "eleven" in low or "sarvam" in low)
                        else llm_provider
                    )
                    record_alert(provider, msg)

    return UsageObserver()
