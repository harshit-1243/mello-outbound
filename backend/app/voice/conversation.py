"""Deterministic outbound conversation engine — the practice-mode 'brain'.

The live agent uses Cerebras + the outbound prompt/tools to drive the call. This module is the
no-LLM stand-in (like SimulatedProvider is for telephony): a small intent + state machine that
drives the SAME tools toward the SAME dispositions, so the full goal-driven flow — opening, consent,
confirm/reschedule/cancel, opt-out, busy, wrong-number, AI-disclosure-if-asked — can be run and
tested with zero API calls. Keyword intents accept English, romanized Hindi, and Devanagari.
"""
from __future__ import annotations

import re

from app.db.models import DISPOSITION_FAILED, OBJECTIVE_BOOKING_CONFIRMATION
from app.voice import outbound_tools as T
from app.voice.outbound_prompts import build_opening, disclosure_line

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_TIME_RE = re.compile(r"(\d{1,2}:\d{2})")

# Whole-word intent tokens (matched after normalization). Priority is the order checked in handle().
_OPTOUT = ["stop", "do not call", "dont call", "mat karo", "band karo", "band kar", "call mat karo",
           "unsubscribe", "remove me", "बंद करो", "दोबारा मत", "मत करो"]
_WRONG = ["wrong number", "galat number", "गलत नंबर"]
_ROBOT = ["robot", "recording", "ai", "machine", "bot", "insaan", "इंसान", "real person", "asli aadmi"]
_BUSY = ["busy", "later", "call back", "callback", "baad mein", "abhi nahi", "thodi der", "vyast",
         "बाद में", "अभी नहीं", "व्यस्त"]
_RESCHED = ["reschedule", "change", "badal", "badlna", "shift", "postpone", "doosra time",
            "another time", "बदल", "दूसरा"]
_CANCEL = ["cancel", "rehne do", "nahi chahiye", "रद्द", "नहीं चाहिए"]
_YES = ["haan", "han", "ji", "yes", "yeah", "yep", "yup", "ya", "ok", "okay", "theek", "sahi",
        "confirm", "sure", "bilkul", "perfect", "done", "हाँ", "ठीक", "जी", "सही", "बिल्कुल"]
_NO = ["nahi", "no", "nope", "na", "नहीं", "ना"]

MAX_TURNS = 6


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation (keep digits + Devanagari), pad — for whole-word matching."""
    cleaned = re.sub(r"[^0-9a-zऀ-ॿ]+", " ", (text or "").lower()).strip()
    return f" {cleaned} "


def _has(norm: str, words: list[str]) -> bool:
    return any(f" {w} " in norm for w in words)


class BookingConfirmationConversation:
    """Drives an outbound call toward confirming (or rescheduling/cancelling) one booking."""

    objective_type = OBJECTIVE_BOOKING_CONFIRMATION

    def __init__(self, session, contact, campaign, business_name: str):
        self.session = session
        self.contact = contact
        self.campaign = campaign
        self.business = business_name
        self.ctx = contact.context_json or {}
        self.state = "await_consent"
        self.turns = 0
        self.empty = 0
        self.unknown = 0
        self.resched_tries = 0

    def opening(self) -> str:
        return build_opening(self.objective_type, self.business, self.ctx)

    def timeout_disposition(self) -> str:
        return DISPOSITION_FAILED

    def _service(self) -> str:
        return self.ctx.get("service", "booking")

    def handle(self, text: str) -> T.ToolResult:
        self.turns += 1
        raw = text or ""
        norm = _normalize(raw)

        if not norm.strip():
            self.empty += 1
            if self.empty >= 2:
                return T.log_callback(self.session, self.contact, self.campaign)
            return T.ToolResult(True, f"Hello? क्या आप सुन पा रहे हैं? आपकी {self._service()} booking के बारे में।", end_call=False)

        if self.turns > MAX_TURNS:
            return T.log_callback(self.session, self.contact, self.campaign)

        if _has(norm, _OPTOUT):
            return T.opt_out(self.session, self.contact, self.campaign)
        if _has(norm, _WRONG):
            return T.wrong_number(self.session, self.contact, self.campaign)
        if _has(norm, _ROBOT):
            return T.ToolResult(True, disclosure_line(self.business, self.ctx), end_call=False)
        if _has(norm, _BUSY):
            return T.log_callback(self.session, self.contact, self.campaign)

        if self.state == "await_reschedule":
            d, tm = _DATE_RE.search(raw), _TIME_RE.search(raw)
            if d and tm:
                return T.reschedule_booking(self.session, self.contact, self.campaign, new_date=d.group(1), new_time=tm.group(1))
            self.resched_tries += 1
            if self.resched_tries >= 2:
                return T.log_callback(self.session, self.contact, self.campaign)
            return T.ToolResult(True, "किस date और time पे? जैसे 2030-07-04 19:00.", end_call=False)

        if _has(norm, _RESCHED):
            self.state = "await_reschedule"
            return T.ToolResult(True, "ज़रूर — किस दिन और time पे करना चाहेंगे?", end_call=False)
        if _has(norm, _CANCEL):
            return T.cancel_booking(self.session, self.contact, self.campaign)
        if _has(norm, _YES):
            return T.confirm_booking(self.session, self.contact, self.campaign)
        if _has(norm, _NO):
            return T.cancel_booking(self.session, self.contact, self.campaign)

        self.unknown += 1
        if self.unknown >= 3:
            return T.log_callback(self.session, self.contact, self.campaign)
        return T.ToolResult(True, f"माफ़ कीजिए, समझ नहीं आया — क्या आपकी {self._service()} booking ठीक है?", end_call=False)
