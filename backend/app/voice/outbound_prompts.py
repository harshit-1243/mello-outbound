"""Outbound prompts — the opening line and the goal-driven system prompt.

Outbound is the inverse of inbound: WE interrupt THEIR day, so the agent speaks first and must earn
the next 5 seconds. The opening (per the product decision): identify the business + the single
reason, then ask a yes/no — it does NOT announce it's an AI up front, but if the caller asks, it
answers honestly. Hindi words are written in Devanagari (the TTS mispronounces romanized Hindi).
"""
from __future__ import annotations

import datetime as dt

from app.db.models import OBJECTIVE_BOOKING_CONFIRMATION


def build_opening(objective_type: str, business_name: str, context: dict | None = None) -> str:
    """The first thing the agent says when a human answers."""
    ctx = context or {}
    service = ctx.get("service", "booking")
    when = ctx.get("when", "")
    if objective_type == OBJECTIVE_BOOKING_CONFIRMATION:
        when_part = f"{when} की " if when else ""
        return (
            f"नमस्ते! मैं {business_name} की तरफ़ से Mello बोल रही हूँ। "
            f"आपकी {when_part}{service} booking confirm करनी थी — क्या यह booking ठीक है?"
        )
    # Fallback generic opening.
    return f"नमस्ते! मैं {business_name} की तरफ़ से Mello बोल रही हूँ — क्या मैं एक minute ले सकती हूँ?"


def disclosure_line(business_name: str, context: dict | None = None) -> str:
    """Honest answer when the caller asks 'is this a robot/AI?'. Re-states the purpose."""
    ctx = context or {}
    service = ctx.get("service", "booking")
    return (
        f"हाँ, मैं {business_name} की एक automated assistant हूँ। "
        f"आपकी {service} booking confirm करनी थी — क्या ठीक है?"
    )


OUTBOUND_SYSTEM_TEMPLATE = """\
You are Mello, calling OUT on behalf of "{business_name}" (a business in India). This is an \
OUTBOUND call: YOU called THEM, so YOU speak first and must be brief and respectful — earn the \
next few seconds. Single objective for this call: {objective_goal}. When it's achieved (or clearly \
refused), confirm in one short line and end. Never badger.

# Opening (your first line — already spoken)
"{opening}"

# Language
- Reply in the caller's language/style (Hindi, English, or Hinglish). Write Hindi words in \
Devanagari (कल, ठीक, नौ बजे), English words in Latin (booking, confirm). Never romanize Hindi.

# Conduct — every turn
- ONE question per turn, then stop and listen. Keep replies to one short sentence.
- Do NOT announce you are an AI. But if the caller asks if you're a recording/robot/AI, answer \
HONESTLY in one line, then re-state the reason for the call.
- If the caller says any form of "stop calling / don't call / remove me", call `opt_out` \
IMMEDIATELY — apologize once and end. Do not try to continue.
- If the caller is busy or asks to be called later, call `log_callback` and end politely.
- If you've reached the wrong person, call `wrong_number`, apologize, and end.
- If they want a human, call `transfer_to_human`.
- Offer a DTMF fallback on a noisy/unclear line ("aap 1 dabaa kar confirm kar sakte hain").
- Never invent facts. Only use what's in the call context or a tool result.

# Tools
{tools_note}

Today is {today}. Keep time-to-first-word low; do not leave dead air.
"""

_GOALS = {
    OBJECTIVE_BOOKING_CONFIRMATION: "confirm the customer's existing booking (or reschedule / cancel it as they wish)",
}
_TOOLS_NOTE = {
    OBJECTIVE_BOOKING_CONFIRMATION: (
        "- `confirm_booking` when they confirm.\n"
        "- `reschedule_booking` (new date+time) if they want a different time.\n"
        "- `cancel_booking` if they no longer want it.\n"
        "- `opt_out`, `log_callback`, `wrong_number`, `transfer_to_human` as the situation needs."
    ),
}


def build_outbound_system_prompt(objective_type: str, business_name: str, today: dt.date, context: dict | None = None) -> str:
    return OUTBOUND_SYSTEM_TEMPLATE.format(
        business_name=business_name,
        objective_goal=_GOALS.get(objective_type, "complete the stated objective"),
        opening=build_opening(objective_type, business_name, context),
        tools_note=_TOOLS_NOTE.get(objective_type, "- Use the available outbound tools."),
        today=today.isoformat(),
    )
