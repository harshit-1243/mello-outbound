"""Mello OUTBOUND voice agent — local browser harness (mic).

Unlike the inbound bot (which waits for the caller), this is a real outbound call: Mello SPEAKS
FIRST with the campaign's opening, then drives the conversation to its objective. It picks the next
pending contact from the seeded outbound campaign, so confirming/rescheduling updates that contact
on the dashboard's Outbound section live.

Run (after pasting CEREBRAS_API_KEY + SARVAM_API_KEY in backend/.env, and seeding:
`python -m app.seed` then `python -m app.seed_outbound`):

    python -m app.voice.outbound_bot

Open the printed URL (default http://localhost:7860), click Connect, allow the mic — Mello calls you.
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from sqlalchemy import select

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import TransportParams

from app.booking.service import BookingService
from app.db.base import SessionLocal
from app.db.models import CONTACT_PENDING, Campaign, Client, OutboundContact
from app.voice.call_logger import CallLogger
from app.voice.outbound_pipeline_tools import build_outbound_tools_schema, register_outbound_tools
from app.voice.outbound_prompts import build_opening, build_outbound_system_prompt
from app.voice.providers import make_llm, make_stt, make_tts
from app.voice.usage import make_usage_observer

transport_params = {
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        vad_analyzer=SileroVADAnalyzer(params=VADParams(start_secs=0.2, stop_secs=1.0)),
    ),
}


def _demo_target() -> tuple[int, int, int, str, str, dict, str]:
    """Pick the contact Mello will 'call': the next pending one in the seeded campaign.

    Returns (contact_id, campaign_id, client_id, business_name, objective_type, context, phone).
    """
    db = SessionLocal()
    try:
        contact = (
            db.scalars(select(OutboundContact).where(OutboundContact.state == CONTACT_PENDING).order_by(OutboundContact.id)).first()
            or db.scalars(select(OutboundContact).order_by(OutboundContact.id)).first()
        )
        if contact is None:
            raise RuntimeError("No outbound contacts. Seed them first:  python -m app.seed_outbound")
        campaign = db.get(Campaign, contact.campaign_id)
        client = db.get(Client, contact.client_id)
        return (
            contact.id, campaign.id, contact.client_id,
            client.business_name if client else "Mello",
            campaign.objective_type, dict(contact.context_json or {}), contact.phone,
        )
    finally:
        db.close()


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(runner_args, transport_params)

    stt = make_stt()
    llm = make_llm()
    tts = make_tts()

    contact_id, campaign_id, client_id, business_name, objective_type, ctx, phone = _demo_target()
    with SessionLocal() as db:
        today = BookingService(db, client_id).today

    context = LLMContext(
        messages=[{"role": "system", "content": build_outbound_system_prompt(objective_type, business_name, today, ctx)}],
        tools=build_outbound_tools_schema(objective_type),
    )

    call_logger = CallLogger(client_id, phone)
    aggregators = LLMContextAggregatorPair(context)
    user_agg = aggregators.user()
    assistant_agg = aggregators.assistant()

    @user_agg.event_handler("on_user_turn_stopped")
    async def _on_user_turn(_agg, _strategy, message):  # noqa: ANN001
        try:
            call_logger.log_turn("user", getattr(message, "content", "") or "")
        except Exception:  # noqa: BLE001
            pass

    @assistant_agg.event_handler("on_assistant_turn_stopped")
    async def _on_assistant_turn(_agg, message):  # noqa: ANN001
        try:
            call_logger.log_turn("assistant", getattr(message, "content", "") or "")
        except Exception:  # noqa: BLE001
            pass

    pipeline = Pipeline([transport.input(), stt, user_agg, llm, tts, transport.output(), assistant_agg])
    observers = [obs for obs in [make_usage_observer()] if obs is not None]
    task = PipelineTask(pipeline, params=PipelineParams(enable_metrics=True), observers=observers)
    # Register tools now that the task exists, so a terminal tool can speak its line and hang up.
    register_outbound_tools(llm, contact_id, campaign_id, call_logger, task=task)

    @llm.event_handler("on_completion_timeout")
    async def _on_llm_timeout(_service):
        await task.queue_frames([TTSSpeakFrame("Sorry, give me one moment.")])

    spoke = False

    @transport.event_handler("on_client_connected")
    async def _on_connected(_transport, _client):
        # Outbound = AGENT SPEAKS FIRST. Play the opening the instant the call connects (once).
        nonlocal spoke
        if spoke:
            return
        spoke = True
        opening = build_opening(objective_type, business_name, ctx)
        context.messages.append({"role": "assistant", "content": opening})
        call_logger.log_turn("assistant", opening)
        await task.queue_frames([TTSSpeakFrame(opening)])

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_transport, _client):
        try:
            record = call_logger.close()
            print(f"[Mello-Outbound] call logged → outcome={record.outcome}, db_id={record.call_id}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[Mello-Outbound] call_logger.close failed: {exc}", flush=True)
        await task.cancel()

    await PipelineRunner(handle_sigint=runner_args.handle_sigint).run(task)


if __name__ == "__main__":
    from app.config import settings

    _db = settings.database_url
    _target = "local SQLite" if _db.startswith("sqlite") else _db.split("@")[-1]
    print(f"[Mello-Outbound] LLM = {settings.llm_provider} ({settings.cerebras_model}) · DB = {_target}")
    print("[Mello-Outbound] Mello will speak first when you connect.")

    from pipecat.runner.run import main

    main()
