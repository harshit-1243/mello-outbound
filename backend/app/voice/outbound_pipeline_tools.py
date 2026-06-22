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
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.services.llm_service import FunctionCallParams, FunctionCallResultProperties

from app.db.base import SessionLocal
from app.db.models import (
    AMD_HUMAN,
    OBJECTIVE_BOOKING_CONFIRMATION,
    OBJECTIVE_FEEDBACK,
    OBJECTIVE_LEAD_QUALIFICATION,
    OBJECTIVE_MEMBERSHIP_RENEWAL,
    OBJECTIVE_NO_SHOW_FOLLOWUP,
    OBJECTIVE_PROMO_OFFER,
    OBJECTIVE_REACTIVATION,
    CallAttempt,
    Campaign,
    OutboundContact,
)
from app.voice import dispositions
from app.voice import outbound_tools as OT

logger = logging.getLogger(__name__)

# Every outbound tool the LLM can ever call, by name. The per-objective schema (below) hands the
# model only the relevant subset — but the dispatch + handlers cover all of them, so a tool is never
# named in a prompt without a working implementation behind it.
_ALL_SCHEMAS = {
    "confirm_booking": FunctionSchema(name="confirm_booking", description="Call when the customer confirms the booking is fine.", properties={}, required=[]),
    "reschedule_booking": FunctionSchema(
        name="reschedule_booking",
        description="Move the booking to a new date/time the customer gives.",
        properties={
            "new_date": {"type": "string", "description": "New date YYYY-MM-DD"},
            "new_time": {"type": "string", "description": "New 24-hour time HH:MM"},
        },
        required=["new_date", "new_time"],
    ),
    "cancel_booking": FunctionSchema(name="cancel_booking", description="Cancel the booking if the customer no longer wants it.", properties={}, required=[]),
    "mark_renewal": FunctionSchema(name="mark_renewal", description="The member agrees to renew their membership.", properties={}, required=[]),
    "log_interest": FunctionSchema(name="log_interest", description="The customer is interested / wants to proceed (book a visit, take the offer, rebook).", properties={}, required=[]),
    "record_feedback": FunctionSchema(name="record_feedback", description="The customer shared their feedback.", properties={}, required=[]),
    "decline": FunctionSchema(name="decline", description="The customer is not interested — close politely (no booking change).", properties={}, required=[]),
    "opt_out": FunctionSchema(name="opt_out", description="Call IMMEDIATELY if the customer says stop calling / do not call / remove me.", properties={}, required=[]),
    "log_callback": FunctionSchema(name="log_callback", description="The customer is busy or asks to be called back later.", properties={}, required=[]),
    "wrong_number": FunctionSchema(name="wrong_number", description="Reached the wrong person.", properties={}, required=[]),
    "transfer_to_human": FunctionSchema(name="transfer_to_human", description="The customer wants to speak to a person.", properties={}, required=[]),
}

# Tools offered on every call regardless of objective.
_COMMON = ["opt_out", "log_callback", "wrong_number", "transfer_to_human"]

# Which tools each objective's prompt actually references — MUST stay in sync with
# outbound_prompts._TOOLS_NOTE (the prompt-vs-schema regression test enforces this).
_OBJECTIVE_TOOLS = {
    OBJECTIVE_BOOKING_CONFIRMATION: ["confirm_booking", "reschedule_booking", "cancel_booking", *_COMMON],
    OBJECTIVE_MEMBERSHIP_RENEWAL: ["mark_renewal", "decline", *_COMMON],
    OBJECTIVE_REACTIVATION: ["log_interest", "decline", *_COMMON],
    OBJECTIVE_LEAD_QUALIFICATION: ["log_interest", "decline", *_COMMON],
    OBJECTIVE_NO_SHOW_FOLLOWUP: ["log_interest", "decline", *_COMMON],
    OBJECTIVE_PROMO_OFFER: ["log_interest", "decline", *_COMMON],
    OBJECTIVE_FEEDBACK: ["record_feedback", "decline", *_COMMON],
}

_DISPATCH = {
    "confirm_booking": lambda db, c, camp, a: OT.confirm_booking(db, c, camp),
    "reschedule_booking": lambda db, c, camp, a: OT.reschedule_booking(db, c, camp, new_date=a.get("new_date"), new_time=a.get("new_time")),
    "cancel_booking": lambda db, c, camp, a: OT.cancel_booking(db, c, camp),
    "mark_renewal": lambda db, c, camp, a: OT.mark_renewal(db, c, camp),
    "log_interest": lambda db, c, camp, a: OT.log_interest(db, c, camp),
    "record_feedback": lambda db, c, camp, a: OT.record_feedback(db, c, camp),
    "decline": lambda db, c, camp, a: OT.decline(db, c, camp),
    "opt_out": lambda db, c, camp, a: OT.opt_out(db, c, camp),
    "log_callback": lambda db, c, camp, a: OT.log_callback(db, c, camp),
    "wrong_number": lambda db, c, camp, a: OT.wrong_number(db, c, camp),
    "transfer_to_human": lambda db, c, camp, a: OT.transfer_to_human(db, c, camp),
}


def build_outbound_tools_schema(objective_type: str = OBJECTIVE_BOOKING_CONFIRMATION) -> ToolsSchema:
    """Hand the LLM only the tools its objective's prompt references (+ the common ones)."""
    names = _OBJECTIVE_TOOLS.get(objective_type, _OBJECTIVE_TOOLS[OBJECTIVE_BOOKING_CONFIRMATION])
    return ToolsSchema(standard_tools=[_ALL_SCHEMAS[n] for n in names])


def _run(contact_id: int, campaign_id: int, name: str, args: dict) -> dict:
    db = SessionLocal()
    try:
        contact = db.get(OutboundContact, contact_id)
        campaign = db.get(Campaign, campaign_id)
        if contact is None or campaign is None:
            return {"ok": False, "message": "Sorry, I lost the booking details on my side."}
        tr = _DISPATCH[name](db, contact, campaign, args or {})
        mirror = None
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
            # snapshot what the Supabase mirror needs while the session is open
            mirror = {
                "campaign_name": campaign.name, "objective_type": campaign.objective_type,
                "name": contact.name, "phone": contact.phone,
                "disposition": tr.disposition, "state": contact.state,
            }
        db.commit()
        if mirror is not None:  # best-effort: also land on the shared Supabase dashboard
            from app.voice.supabase_sync import sync_outcome
            sync_outcome(**mirror)
        return {"ok": tr.ok, "message": tr.message, "done": tr.end_call}
    finally:
        db.close()


def register_outbound_tools(llm, contact_id: int, campaign_id: int, call_logger=None, task=None) -> None:
    async def handler(params: FunctionCallParams):
        try:
            result = await asyncio.to_thread(_run, contact_id, campaign_id, params.function_name, params.arguments or {})
        except Exception:  # noqa: BLE001 — never let the bot hang on a tool crash
            logger.error("Outbound tool %s crashed:\n%s", params.function_name, traceback.format_exc())
            result = {"ok": False, "message": "Something went wrong — I'll have the team follow up."}

        terminal = bool(result.get("done"))
        if call_logger is not None and terminal:
            try:
                call_logger.mark_booking()
            except Exception:  # noqa: BLE001
                pass

        # Terminal outcome (confirm / decline / opt-out / ...): speak the one closing line and HANG
        # UP. We stop the model from generating another turn (run_llm=False) so the call can't fire a
        # second tool/disposition after the goal is met — the bug where one call logged confirmed AND
        # refused. Non-terminal results (e.g. reschedule slot taken) fall through so the agent can
        # keep going. Needs the pipeline task; without it (or no closing line) we just return.
        if terminal and task is not None:
            closing = result.get("message") or ""

            async def _end_call():
                if closing:
                    await task.queue_frame(TTSSpeakFrame(closing))
                await task.stop_when_done()

            await params.result_callback(
                result, properties=FunctionCallResultProperties(run_llm=False, on_context_updated=_end_call)
            )
            return

        await params.result_callback(result)

    for name in _DISPATCH:
        llm.register_function(name, handler)
