"""Wire the OUTBOUND tools into a Pipecat LLM (the outbound counterpart of pipeline_tools).

When the LLM calls a terminal tool (confirm / reschedule / cancel / opt_out / ...), we run the
matching app.voice.outbound_tools function AND record the outcome on the contact + a CallAttempt —
so the dashboard's Outbound section updates live (contact pill flips, metrics move).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import traceback

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

from app.db.base import SessionLocal
from app.db.models import AMD_HUMAN, CallAttempt, Campaign, OutboundContact
from app.voice import dispositions
from app.voice import outbound_tools as OT

logger = logging.getLogger(__name__)

# Tools for the booking-confirmation objective (the demo objective).
_SCHEMAS = [
    FunctionSchema(name="confirm_booking", description="Call when the customer confirms the booking is fine.", properties={}, required=[]),
    FunctionSchema(
        name="reschedule_booking",
        description="Move the booking to a new date/time the customer gives.",
        properties={
            "new_date": {"type": "string", "description": "New date YYYY-MM-DD"},
            "new_time": {"type": "string", "description": "New 24-hour time HH:MM"},
        },
        required=["new_date", "new_time"],
    ),
    FunctionSchema(name="cancel_booking", description="Cancel the booking if the customer no longer wants it.", properties={}, required=[]),
    FunctionSchema(name="opt_out", description="Call IMMEDIATELY if the customer says stop calling / do not call / remove me.", properties={}, required=[]),
    FunctionSchema(name="log_callback", description="The customer is busy or asks to be called back later.", properties={}, required=[]),
    FunctionSchema(name="wrong_number", description="Reached the wrong person.", properties={}, required=[]),
    FunctionSchema(name="transfer_to_human", description="The customer wants to speak to a person.", properties={}, required=[]),
]

_DISPATCH = {
    "confirm_booking": lambda db, c, camp, a: OT.confirm_booking(db, c, camp),
    "reschedule_booking": lambda db, c, camp, a: OT.reschedule_booking(db, c, camp, new_date=a.get("new_date"), new_time=a.get("new_time")),
    "cancel_booking": lambda db, c, camp, a: OT.cancel_booking(db, c, camp),
    "opt_out": lambda db, c, camp, a: OT.opt_out(db, c, camp),
    "log_callback": lambda db, c, camp, a: OT.log_callback(db, c, camp),
    "wrong_number": lambda db, c, camp, a: OT.wrong_number(db, c, camp),
    "transfer_to_human": lambda db, c, camp, a: OT.transfer_to_human(db, c, camp),
}


def build_outbound_tools_schema() -> ToolsSchema:
    return ToolsSchema(standard_tools=_SCHEMAS)


def _run(contact_id: int, campaign_id: int, name: str, args: dict) -> dict:
    db = SessionLocal()
    try:
        contact = db.get(OutboundContact, contact_id)
        campaign = db.get(Campaign, campaign_id)
        if contact is None or campaign is None:
            return {"ok": False, "message": "Sorry, I lost the booking details on my side."}
        tr = _DISPATCH[name](db, contact, campaign, args or {})
        if tr.disposition is not None:  # terminal — record it so the dashboard updates
            contact.attempt_count += 1
            contact.last_disposition = tr.disposition
            decision = dispositions.plan(
                tr.disposition, attempt_count=contact.attempt_count, max_attempts=campaign.max_attempts,
                voicemail_count=0, retry_policy=campaign.retry_policy or {}, now=dt.datetime.utcnow(),
            )
            contact.state = decision.state
            contact.leased_until = None
            db.add(CallAttempt(
                client_id=contact.client_id, campaign_id=campaign.id, contact_id=contact.id,
                answered=True, amd_result=AMD_HUMAN, disposition=tr.disposition, duration_s=0, cost_inr=0,
            ))
        db.commit()
        return {"ok": tr.ok, "message": tr.message, "done": tr.end_call}
    finally:
        db.close()


def register_outbound_tools(llm, contact_id: int, campaign_id: int, call_logger=None) -> None:
    async def handler(params: FunctionCallParams):
        try:
            result = await asyncio.to_thread(_run, contact_id, campaign_id, params.function_name, params.arguments or {})
        except Exception:  # noqa: BLE001 — never let the bot hang on a tool crash
            logger.error("Outbound tool %s crashed:\n%s", params.function_name, traceback.format_exc())
            result = {"ok": False, "message": "Something went wrong — I'll have the team follow up."}
        if call_logger is not None and result.get("done"):
            try:
                call_logger.mark_booking()
            except Exception:  # noqa: BLE001
                pass
        await params.result_callback(result)

    for s in _SCHEMAS:
        llm.register_function(s.name, handler)
