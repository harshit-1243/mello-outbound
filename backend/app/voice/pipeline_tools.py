"""Wire the booking tools into a Pipecat LLM (framework-specific glue over app.voice.tools).

- ``build_tools_schema`` converts the vendor-neutral tool defs into Pipecat's ToolsSchema.
- ``register_tools`` attaches handlers that run the (synchronous) booking engine off the event
  loop via ``asyncio.to_thread`` and return the result to the LLM.
"""
from __future__ import annotations

import asyncio
import logging
import traceback

from sqlalchemy import select

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

from app.db.base import SessionLocal
from app.db.models import Client, Facility
from app.voice.tools import ANTHROPIC_TOOLS, dispatch

TOOL_NAMES = [t["name"] for t in ANTHROPIC_TOOLS]

logger = logging.getLogger(__name__)


def build_tools_schema() -> ToolsSchema:
    return ToolsSchema(
        standard_tools=[
            FunctionSchema(
                name=t["name"],
                description=t["description"],
                properties=t["input_schema"]["properties"],
                required=t["input_schema"]["required"],
            )
            for t in ANTHROPIC_TOOLS
        ]
    )


def _run_tool(client_id: int, name: str, arguments: dict) -> dict:
    db = SessionLocal()
    try:
        return dispatch(db, client_id, name, arguments)
    finally:
        db.close()


def register_tools(llm, client_id: int, call_logger=None) -> None:
    """Register one handler per tool name; each dispatches to the booking engine in a thread.

    ``call_logger`` (optional): when a create_booking call succeeds, flag the call as 'booked' so
    the transcript log records the right outcome.
    """

    async def handler(params: FunctionCallParams):
        # CRITICAL: the LLM is paused until result_callback fires. If the tool raises an
        # exception that dispatch() doesn't catch, the callback would never run and the bot
        # would go permanently silent mid-call. So we catch EVERYTHING here and always hand a
        # result back — an error payload the LLM can speak gracefully instead of hanging.
        try:
            result = await asyncio.to_thread(
                _run_tool, client_id, params.function_name, params.arguments
            )
        except Exception:  # noqa: BLE001 — last line of defence; the bot must never hang.
            logger.error(
                "Tool %s crashed with args %r:\n%s",
                params.function_name,
                params.arguments,
                traceback.format_exc(),
            )
            result = {
                "error": "tool_failed",
                "message": "Something went wrong on our side. Please ask the caller to repeat.",
            }
        if call_logger is not None and params.function_name == "create_booking" and result.get("booked"):
            try:
                call_logger.mark_booking()
            except Exception:  # noqa: BLE001
                pass
        await params.result_callback(result)

    for name in TOOL_NAMES:
        llm.register_function(name, handler)


def demo_client_context() -> tuple[int, str, dict | None]:
    """For the local harness: the first seeded client as the 'business' answering the call.

    Returns (client_id, business_name, facility_info) where facility_info carries the real
    address/hours for the system prompt so the agent never invents them.
    """
    db = SessionLocal()
    try:
        client = db.scalars(select(Client).order_by(Client.id)).first()
        if client is None:
            raise RuntimeError("No client found. Seed demo data first:  python -m app.seed")
        facility = db.scalars(
            select(Facility).where(Facility.client_id == client.id).order_by(Facility.id)
        ).first()
        facility_info = None
        if facility is not None:
            facility_info = {
                "address": facility.address,
                "opening": facility.opening_time.strftime("%H:%M"),
                "closing": facility.closing_time.strftime("%H:%M"),
            }
        return client.id, client.business_name, facility_info
    finally:
        db.close()
