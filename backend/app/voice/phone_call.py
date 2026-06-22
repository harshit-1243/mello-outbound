"""Run the OUTBOUND voice agent over a real Twilio phone call (Media Streams).

Twilio dials your verified number; on answer it opens a WebSocket to /ws/twilio carrying the audio.
This runs the same goal-driven outbound pipeline (Cerebras + Sarvam) as the browser bot, but with
the Twilio serializer (8 kHz μ-law) — Mello speaks first, drives the call, and its tools update the
dashboard. Triggered only via the allowlisted /clients/{id}/test-call endpoint.
"""
from __future__ import annotations

import json

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from app.booking.service import BookingService
from app.config import settings
from app.db.base import SessionLocal
from app.db.models import Campaign, Client, OutboundContact
from app.voice.call_logger import CallLogger
from app.voice.outbound_pipeline_tools import build_outbound_tools_schema, register_outbound_tools
from app.voice.outbound_prompts import build_opening, build_outbound_system_prompt
from app.voice.providers import make_llm, make_stt, make_tts


def _resolve_target(contact_id: int | None):
    """Load (contact_id, campaign_id, client_id, business, objective, context, phone) for the call."""
    db = SessionLocal()
    try:
        contact = db.get(OutboundContact, contact_id) if contact_id else None
        if contact is None:
            from app.voice.outbound_bot import _demo_target  # fall back to the next pending contact
            return _demo_target()
        campaign = db.get(Campaign, contact.campaign_id)
        client = db.get(Client, contact.client_id)
        return (
            contact.id, campaign.id, contact.client_id,
            client.business_name if client else "Mello",
            campaign.objective_type, dict(contact.context_json or {}), contact.phone,
        )
    finally:
        db.close()


async def run_twilio_call(websocket) -> None:
    await websocket.accept()

    # Twilio's first two frames: "connected" then "start" (carries streamSid/callSid + parameters).
    stream = websocket.iter_text()
    await stream.__anext__()
    start = json.loads(await stream.__anext__())
    info = start["start"]
    stream_sid = info["streamSid"]
    call_sid = info.get("callSid")
    params = info.get("customParameters") or {}
    contact_id = int(params["contact_id"]) if params.get("contact_id") else None

    contact_id, campaign_id, client_id, business, objective, ctx, phone = _resolve_target(contact_id)
    with SessionLocal() as db:
        today = BookingService(db, client_id).today

    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
    )
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(start_secs=0.2, stop_secs=1.0)),
            serializer=serializer,
        ),
    )

    stt = make_stt()
    llm = make_llm()
    tts = make_tts()

    context = LLMContext(
        messages=[{"role": "system", "content": build_outbound_system_prompt(objective, business, today, ctx)}],
        tools=build_outbound_tools_schema(),
    )
    call_logger = CallLogger(client_id, phone)
    register_outbound_tools(llm, contact_id, campaign_id, call_logger)
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
    task = PipelineTask(pipeline, params=PipelineParams(enable_metrics=True))

    spoke = False

    @transport.event_handler("on_client_connected")
    async def _on_connected(_transport, _client):
        nonlocal spoke
        if spoke:
            return
        spoke = True
        opening = build_opening(objective, business, ctx)
        context.messages.append({"role": "assistant", "content": opening})
        call_logger.log_turn("assistant", opening)
        await task.queue_frames([TTSSpeakFrame(opening)])

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_transport, _client):
        try:
            call_logger.close()
        except Exception:  # noqa: BLE001
            pass
        await task.cancel()

    await PipelineRunner(handle_sigint=False).run(task)
