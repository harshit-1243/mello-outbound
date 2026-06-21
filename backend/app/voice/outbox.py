"""Vendor-agnostic confirmation outbox.

On a successful outcome (confirmed / rescheduled) the dialer fires a confirmation here. Real
delivery (WhatsApp via Interakt/Wati, or SMS via a DLT-registered template) is wired later; until
then this LOGS the message and returns a stub payload — graceful, exactly like the inbound side.
Keeping it behind one function means the channel can be swapped without touching the dialer.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("mello.outbound.outbox")


def send_confirmation(session, contact, campaign, channel: str = "whatsapp") -> dict:
    payload = {
        "channel": channel,
        "to": contact.phone,
        "objective": campaign.objective_type,
        "sent": False,   # True once a real provider is wired
        "stub": True,
    }
    logger.info("outbox confirmation (stub): %s", payload)
    return payload
