"""Outbound prompts — the opening line and the goal-driven system prompt.

Outbound is the inverse of inbound: WE interrupt THEIR day, so the agent speaks first and must earn
the next 5 seconds. The opening (per the product decision): identify the business + the single
reason, then ask a yes/no — it does NOT announce it's an AI up front, but if the caller asks, it
answers honestly. Hindi words are written in Devanagari (the TTS mispronounces romanized Hindi).
"""
from __future__ import annotations

import datetime as dt

from app.db.models import (
    OBJECTIVE_BOOKING_CONFIRMATION,
    OBJECTIVE_FEEDBACK,
    OBJECTIVE_LEAD_QUALIFICATION,
    OBJECTIVE_MEMBERSHIP_RENEWAL,
    OBJECTIVE_NO_SHOW_FOLLOWUP,
    OBJECTIVE_PROMO_OFFER,
    OBJECTIVE_REACTIVATION,
)


def build_opening(objective_type: str, business_name: str, context: dict | None = None) -> str:
    """The first thing the agent says when a human answers (English-first; mirrors to Hindi later)."""
    ctx = context or {}
    service = ctx.get("service", "service")
    when = ctx.get("when", "")
    when_part = f"{when} " if when else ""
    b = business_name

    if objective_type == OBJECTIVE_BOOKING_CONFIRMATION:
        svc = ctx.get("service", "booking")
        return (f"Hi! This is Mello calling from {b}. I just wanted to confirm your "
                f"{when_part}{svc} booking — is that still good for you?")
    if objective_type == OBJECTIVE_MEMBERSHIP_RENEWAL:
        return (f"Hi! This is Mello from {b}. Your membership is coming up for renewal — "
                f"would you like me to help you renew it?")
    if objective_type == OBJECTIVE_REACTIVATION:
        return (f"Hi! This is Mello from {b}. It's been a while and we've missed you — "
                f"can I help you book your next {service} visit?")
    if objective_type == OBJECTIVE_LEAD_QUALIFICATION:
        return (f"Hi! This is Mello from {b}. You'd shown interest in our {service} — "
                f"is now a good time for a quick word?")
    if objective_type == OBJECTIVE_NO_SHOW_FOLLOWUP:
        return (f"Hi! This is Mello from {b}. We missed you at your {when_part}appointment — "
                f"shall I help you rebook it?")
    if objective_type == OBJECTIVE_PROMO_OFFER:
        return (f"Hi! This is Mello from {b}. We have a special offer on {service} for you — "
                f"would you like to hear about it?")
    if objective_type == OBJECTIVE_FEEDBACK:
        return (f"Hi! This is Mello from {b}. Thanks for visiting recently — "
                f"do you have twenty seconds to share quick feedback?")
    return f"Hi! This is Mello calling from {b} — do you have a quick minute?"


def disclosure_line(business_name: str, context: dict | None = None) -> str:
    """Honest answer when the caller asks 'is this a robot/AI?'. Re-states intent generically."""
    return (
        f"Yes, I'm an automated assistant from {business_name}. "
        f"I'll keep this really quick — is that okay?"
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

_COMMON_TOOLS = "- `opt_out`, `log_callback`, `wrong_number`, `transfer_to_human` as the situation needs."

_GOALS = {
    OBJECTIVE_BOOKING_CONFIRMATION: "confirm the customer's existing booking (or reschedule / cancel it as they wish)",
    OBJECTIVE_MEMBERSHIP_RENEWAL: "get the member to renew their membership",
    OBJECTIVE_REACTIVATION: "win back a lapsed customer — get them to book their next visit",
    OBJECTIVE_LEAD_QUALIFICATION: "qualify an interested lead and book a visit / callback",
    OBJECTIVE_NO_SHOW_FOLLOWUP: "rebook a customer who missed their appointment",
    OBJECTIVE_PROMO_OFFER: "share the current offer and get the customer to take it up",
    OBJECTIVE_FEEDBACK: "collect brief post-visit feedback",
}
_TOOLS_NOTE = {
    OBJECTIVE_BOOKING_CONFIRMATION: (
        "- `confirm_booking` when they confirm.\n"
        "- `reschedule_booking` (new date+time) if they want a different time.\n"
        "- `cancel_booking` if they no longer want it.\n" + _COMMON_TOOLS
    ),
    OBJECTIVE_MEMBERSHIP_RENEWAL: "- `mark_renewal` when they agree to renew.\n- `decline` if not.\n" + _COMMON_TOOLS,
    OBJECTIVE_REACTIVATION: "- `log_interest` when they want to book a visit.\n- `decline` if not.\n" + _COMMON_TOOLS,
    OBJECTIVE_LEAD_QUALIFICATION: "- `log_interest` when they're interested.\n- `decline` if not.\n" + _COMMON_TOOLS,
    OBJECTIVE_NO_SHOW_FOLLOWUP: "- `log_interest` when they want to rebook.\n- `decline` if not.\n" + _COMMON_TOOLS,
    OBJECTIVE_PROMO_OFFER: "- `log_interest` when they take up the offer.\n- `decline` if not.\n" + _COMMON_TOOLS,
    OBJECTIVE_FEEDBACK: "- `record_feedback` once they share feedback.\n- `decline` if they'd rather not.\n" + _COMMON_TOOLS,
}


def build_outbound_system_prompt(objective_type: str, business_name: str, today: dt.date, context: dict | None = None) -> str:
    return OUTBOUND_SYSTEM_TEMPLATE.format(
        business_name=business_name,
        objective_goal=_GOALS.get(objective_type, "complete the stated objective"),
        opening=build_opening(objective_type, business_name, context),
        tools_note=_TOOLS_NOTE.get(objective_type, "- Use the available outbound tools."),
        today=today.isoformat(),
    )
