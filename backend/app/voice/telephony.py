"""Telephony provider abstraction — keeps the dialer independent of Twilio/Exotel.

The dialer talks to this interface only, so swapping the real carrier in later (Twilio now, Exotel
later) changes nothing above it. ``SimulatedProvider`` is "practice mode": it places no real call
and returns a fixed, configurable outcome, so the whole dialer + accounting + state machine can be
built and tested with no accounts and no risk of ringing a real phone.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.db.models import AMD_HUMAN, DISPOSITION_CONFIRMED


@dataclass
class DialResult:
    """What one placed call produced (real or simulated)."""

    provider_call_sid: str
    answered: bool
    amd_result: str       # human | voicemail | ivr | unknown
    disposition: str      # confirmed | no_answer | busy | voicemail | ...
    duration_s: int
    cost_inr: float


class TelephonyProvider(Protocol):
    def place_call(self, to: str, context: dict | None = None) -> DialResult: ...


class SimulatedProvider:
    """Practice-mode carrier: no dialing. Returns a fixed outcome you configure per test/run."""

    def __init__(
        self,
        *,
        answered: bool = True,
        amd_result: str = AMD_HUMAN,
        disposition: str = DISPOSITION_CONFIRMED,
        duration_s: int = 35,
        cost_inr: float = 1.5,
    ):
        self._answered = answered
        self._amd = amd_result
        self._disposition = disposition
        self._duration = duration_s
        self._cost = cost_inr

    def place_call(self, to: str, context: dict | None = None) -> DialResult:
        return DialResult(
            provider_call_sid=f"SIM-{uuid.uuid4().hex[:12]}",
            answered=self._answered,
            amd_result=self._amd,
            disposition=self._disposition,
            duration_s=self._duration,
            cost_inr=self._cost,
        )
