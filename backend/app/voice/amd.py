"""Answering-machine detection (AMD) policy — decide what to do once a call is answered.

The carrier (Twilio/Exotel) classifies the answer in the first ~2-3s; ``classify_answeredby`` maps
its label to our ``amd_result``, and ``decide`` turns that into an action. The hard rule: a machine
NEVER gets a conversation — only a human reaches the goal-driven bot. Voicemail may get ONE short
TTS message (capped); IVR/unknown is hung up for manual review.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.db.models import (
    AMD_HUMAN,
    AMD_IVR,
    AMD_UNKNOWN,
    AMD_VOICEMAIL,
    DISPOSITION_FAILED,
    DISPOSITION_VOICEMAIL,
)

ACTION_CONVERSE = "converse"            # human → run the bot
ACTION_LEAVE_VOICEMAIL = "leave_voicemail"  # play one TTS message, then hang up
ACTION_HANG_UP = "hang_up"             # machine we won't talk to → end the call


@dataclass(frozen=True)
class AmdDecision:
    action: str
    disposition: str | None  # set for machine outcomes; None for human (the bot sets it)


def classify_answeredby(answered_by: str | None) -> str:
    """Map a carrier AMD label (Twilio AnsweredBy style) to our amd_result."""
    s = (answered_by or "").strip().lower()
    if s == "human":
        return AMD_HUMAN
    if s.startswith("machine"):  # machine_start / machine_end_beep / _silence / _other
        return AMD_VOICEMAIL
    if s == "fax":
        return AMD_IVR
    return AMD_UNKNOWN


def decide(amd_result: str, *, voicemail_count: int = 0, voicemail_max: int = 1) -> AmdDecision:
    """What to do on an answered call. NEVER returns ``converse`` for a machine."""
    if amd_result == AMD_HUMAN:
        return AmdDecision(ACTION_CONVERSE, None)
    if amd_result == AMD_VOICEMAIL:
        if voicemail_count < voicemail_max:
            return AmdDecision(ACTION_LEAVE_VOICEMAIL, DISPOSITION_VOICEMAIL)
        return AmdDecision(ACTION_HANG_UP, DISPOSITION_VOICEMAIL)
    # IVR or unknown → hang up for manual review; never run the LLM against it.
    return AmdDecision(ACTION_HANG_UP, DISPOSITION_FAILED)
