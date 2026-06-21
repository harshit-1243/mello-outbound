"""Disposition handling — decide what a call's outcome means for the contact.

Terminal outcomes (confirmed/refused/rescheduled/opt_out/wrong_number/callback_requested) end the
contact. Retryable ones (no_answer/busy/voicemail/failed) schedule the next attempt with a
per-type backoff, capped by max_attempts (and voicemail by its own cap). The next attempt's time is
just a ``next_attempt_at`` — the dialer's candidate query + the compliance gate guarantee it still
re-passes the calling window before it actually dials. A successful outcome flags a downstream
confirmation (WhatsApp/SMS via the outbox).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.db.models import (
    CONTACT_DONE,
    CONTACT_EXHAUSTED,
    CONTACT_PENDING,
    DISPOSITION_BUSY,
    DISPOSITION_CONFIRMED,
    DISPOSITION_NO_ANSWER,
    DISPOSITION_RESCHEDULED,
    DISPOSITION_VOICEMAIL,
    TERMINAL_DISPOSITIONS,
)

# Default backoffs (overridable per campaign via retry_policy JSON).
_DEFAULTS = {"no_answer_hours": 4, "busy_minutes": 15, "voicemail_hours": 4, "failed_hours": 6, "voicemail_max": 1}
# Outcomes that warrant a confirmation message.
_SUCCESS = {DISPOSITION_CONFIRMED, DISPOSITION_RESCHEDULED}


@dataclass
class RetryDecision:
    terminal: bool
    state: str                       # done | exhausted | pending
    next_attempt_at: dt.datetime | None
    fire_confirmation: bool


def _delay(disposition: str, policy: dict) -> dt.timedelta:
    def g(k):
        return policy.get(k, _DEFAULTS[k])

    if disposition == DISPOSITION_NO_ANSWER:
        return dt.timedelta(hours=g("no_answer_hours"))
    if disposition == DISPOSITION_BUSY:
        return dt.timedelta(minutes=g("busy_minutes"))
    if disposition == DISPOSITION_VOICEMAIL:
        return dt.timedelta(hours=g("voicemail_hours"))
    return dt.timedelta(hours=g("failed_hours"))  # failed / anything else retryable


def plan(disposition, *, attempt_count: int, max_attempts: int, voicemail_count: int, retry_policy: dict, now: dt.datetime) -> RetryDecision:
    """Decide terminal vs retry, the next-attempt time, and whether to send a confirmation."""
    policy = retry_policy or {}

    if disposition in TERMINAL_DISPOSITIONS:
        return RetryDecision(True, CONTACT_DONE, None, disposition in _SUCCESS)

    # Retryable: voicemail has its own cap on top of max_attempts.
    vm_max = int(policy.get("voicemail_max", _DEFAULTS["voicemail_max"]))
    if disposition == DISPOSITION_VOICEMAIL and voicemail_count >= vm_max:
        return RetryDecision(False, CONTACT_EXHAUSTED, None, False)
    if attempt_count >= max_attempts:
        return RetryDecision(False, CONTACT_EXHAUSTED, None, False)
    return RetryDecision(False, CONTACT_PENDING, now + _delay(disposition, policy), False)
