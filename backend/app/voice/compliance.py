"""Compliance gate — runs BEFORE every dial. NON-NEGOTIABLE, no bypass path.

A contact is dial-eligible ONLY if ALL checks pass:
  1. contact is still pending (not done/in-flight/exhausted/skipped)
  2. DLT/registration flag is on (TRAI/TCCCPR — sending entity/headers registered)
  3. not opted out (permanent OptOut list OR per-contact dnc flag) — phone-normalized match
  4. has a lawful consent basis to call
  5. now (contact-local clock) is inside the campaign's calling window
  6. under the per-contact max-attempts cap
  7. under the per-contact per-day cap

``evaluate`` is a PURE function of facts (trivially testable, no hidden state); ``is_dial_eligible``
is the thin DB wrapper that gathers those facts and calls it. The dialer must call this and dial
ONLY when ``eligible`` is True; on False it logs ``reason`` and skips.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.config import settings
from app.db.models import CONTACT_PENDING, CallAttempt, Campaign, OptOut
from app.voice.phone import normalize_phone

# Block reasons (stable strings for logs + tests).
REASON_NOT_PENDING = "not_pending"
REASON_DLT_UNREGISTERED = "dlt_unregistered"
REASON_OPTED_OUT = "opted_out"
REASON_NO_CONSENT = "no_consent"
REASON_OUTSIDE_WINDOW = "outside_window"
REASON_MAX_ATTEMPTS = "max_attempts"
REASON_DAILY_CAP = "daily_cap"


@dataclass(frozen=True)
class GateResult:
    eligible: bool
    reason: str | None = None


def evaluate(
    *,
    now_local: dt.datetime,
    window_start: dt.time,
    window_end: dt.time,
    contact_state: str,
    dlt_registered: bool,
    opted_out: bool,
    consent_basis: str | None,
    attempt_count: int,
    max_attempts: int,
    attempts_today: int,
    daily_cap: int,
) -> GateResult:
    """Pure gate. Deny-first, most-important checks first."""
    if contact_state != CONTACT_PENDING:
        return GateResult(False, REASON_NOT_PENDING)
    if not dlt_registered:
        return GateResult(False, REASON_DLT_UNREGISTERED)
    if opted_out:
        return GateResult(False, REASON_OPTED_OUT)
    if not consent_basis:
        return GateResult(False, REASON_NO_CONSENT)
    t = now_local.time()
    in_window = window_start <= t <= window_end if window_start <= window_end else (t >= window_start or t <= window_end)
    if not in_window:
        return GateResult(False, REASON_OUTSIDE_WINDOW)
    if attempt_count >= max_attempts:
        return GateResult(False, REASON_MAX_ATTEMPTS)
    if attempts_today >= daily_cap:
        return GateResult(False, REASON_DAILY_CAP)
    return GateResult(True)


def _attempts_today(session, contact, now_local: dt.datetime, tz: ZoneInfo) -> int:
    """Count this contact's dials since local midnight (placed_at is stored naive-UTC)."""
    start_local = dt.datetime.combine(now_local.date(), dt.time(0, 0), tzinfo=tz)
    start_utc_naive = start_local.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return session.scalar(
        select(func.count())
        .select_from(CallAttempt)
        .where(CallAttempt.contact_id == contact.id, CallAttempt.placed_at >= start_utc_naive)
    ) or 0


def is_dial_eligible(session, contact, campaign: Campaign | None = None, now: dt.datetime | None = None) -> GateResult:
    """Gather the facts for ``contact`` and run the gate. The only entry point the dialer uses."""
    campaign = campaign or session.get(Campaign, contact.campaign_id)
    tz = ZoneInfo(campaign.timezone or "Asia/Kolkata")
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    now_local = now.astimezone(tz)

    phone = normalize_phone(contact.phone) or contact.phone
    opted_out = bool(contact.dnc) or (
        session.scalar(
            select(func.count())
            .select_from(OptOut)
            .where(OptOut.client_id == contact.client_id, OptOut.phone == phone)
        )
        or 0
    ) > 0

    daily_cap = int((campaign.script_params or {}).get("daily_cap", settings.outbound_daily_cap))

    return evaluate(
        now_local=now_local,
        window_start=campaign.window_start,
        window_end=campaign.window_end,
        contact_state=contact.state,
        dlt_registered=settings.outbound_dlt_registered,
        opted_out=opted_out,
        consent_basis=contact.consent_basis,
        attempt_count=contact.attempt_count,
        max_attempts=campaign.max_attempts,
        attempts_today=_attempts_today(session, contact, now_local, tz),
        daily_cap=daily_cap,
    )
