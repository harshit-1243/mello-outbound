"""Mello voice agent — local browser harness (M2).

Run it (after setting GOOGLE_API_KEY + DEEPGRAM_API_KEY + ELEVENLABS_API_KEY in .env, and seeding
demo data with `python -m app.seed`):

    python -m app.voice.bot

Then open the URL it prints (default http://localhost:7860), click Connect, and talk to Mello in
your browser — no phone number needed. The same pipeline later runs over Exotel (M3) by swapping
the transport; nothing else changes.

Pipeline:  mic → SmallWebRTC → Deepgram Nova-3 (STT) → Gemini/Claude (LLM + 5 booking tools)
           → ElevenLabs/Deepgram (TTS) → speaker, with Silero VAD for turn-taking.
"""
from __future__ import annotations

import sys

# Windows consoles default to cp1252, which can't encode the emoji Pipecat's dev runner prints
# at startup. Force UTF-8 so the runner launches cleanly on Windows.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

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
from app.voice.call_logger import CallLogger
from app.voice.pipeline_tools import build_tools_schema, demo_client_context, register_tools
from app.voice.prompts import build_system_prompt
from app.voice.providers import make_llm, make_stt, make_tts
from app.voice.usage import make_usage_observer

# How each transport is configured. The local browser harness uses "webrtc".
# stop_secs=1.0 — wait a full second of silence before ending the user's turn; the default
# (~0.3 s) fires too aggressively mid-sentence for natural conversational speech.
transport_params = {
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        vad_analyzer=SileroVADAnalyzer(
            params=VADParams(
                start_secs=0.2,   # quick to detect when the user starts speaking
                stop_secs=1.0,    # generous pause before ending their turn
            )
        ),
    ),
}


async def bot(runner_args: RunnerArguments):
    """Entry point the Pipecat dev runner calls when a browser connects."""
    transport = await create_transport(runner_args, transport_params)

    stt = make_stt()
    llm = make_llm()
    tts = make_tts()

    client_id, business_name, facility_info = demo_client_context()
    with SessionLocal() as db:
        today = BookingService(db, client_id).today
    # No caller ID in the browser harness — agent will ask the user for their number.
    # In M3 (Exotel telephony) this is replaced with the real inbound caller ID.
    caller_phone = None

    context = LLMContext(
        messages=[
            {
                "role": "system",
                "content": build_system_prompt(
                    business_name, today, caller_phone=caller_phone, facility=facility_info
                ),
            }
        ],
        tools=build_tools_schema(),
    )

    # Record the conversation: a readable file under backend/call_logs/ plus Call/CallTurn rows
    # so the operator reviews transcripts on the dashboard instead of pasting them.
    call_logger = CallLogger(client_id, caller_phone)
    register_tools(llm, client_id, call_logger)
    aggregators = LLMContextAggregatorPair(context)
    user_agg = aggregators.user()
    assistant_agg = aggregators.assistant()

    # Pipecat 1.3.0: the aggregator pair emits one finalized event per turn (already de-fragmented
    # and stripped of internal markers). This is the supported replacement for TranscriptProcessor.
    @user_agg.event_handler("on_user_turn_stopped")
    async def _on_user_turn(_agg, _strategy, message):  # noqa: ANN001
        try:
            call_logger.log_turn("user", getattr(message, "content", "") or "")
        except Exception:  # noqa: BLE001 — logging must never break a call
            pass

    @assistant_agg.event_handler("on_assistant_turn_stopped")
    async def _on_assistant_turn(_agg, message):  # noqa: ANN001
        try:
            call_logger.log_turn("assistant", getattr(message, "content", "") or "")
        except Exception:  # noqa: BLE001
            pass

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_agg,
            llm,
            tts,
            transport.output(),
            assistant_agg,
        ]
    )

    # A usage observer feeds the free-credit monitor (LLM tokens / TTS chars / quota errors).
    observers = [obs for obs in [make_usage_observer()] if obs is not None]
    task = PipelineTask(pipeline, params=PipelineParams(enable_metrics=True), observers=observers)

    # If a completion still times out after the retry (providers.py), speak a short filler so the
    # caller never hears dead air while we recover.
    @llm.event_handler("on_completion_timeout")
    async def _on_llm_timeout(_service):
        await task.queue_frames([TTSSpeakFrame("Sorry, give me one moment.")])

    greeted = False

    @transport.event_handler("on_client_connected")
    async def _on_connected(_transport, _client):
        # Guard: SmallWebRTC re-fires on_client_connected on an ICE reconnect/renegotiate, which
        # would otherwise re-speak the greeting mid-call. Greet exactly once per call.
        nonlocal greeted
        if greeted:
            return
        greeted = True
        # Push the opening greeting straight to TTS (instant audio, no LLM round-trip) and record
        # it in both context and the transcript (the aggregator doesn't emit an event for it).
        greeting = f"Namaste! Thank you for calling {business_name}. How can I help you today?"
        context.messages.append({"role": "assistant", "content": greeting})
        call_logger.log_turn("assistant", greeting)
        await task.queue_frames([TTSSpeakFrame(greeting)])

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_transport, _client):
        # Stamp duration, derive outcome/summary, and persist the transcript before tearing down.
        try:
            record = call_logger.close()
            print(f"[Mello] call logged → {record.txt_path} (outcome={record.outcome}, db_id={record.call_id})", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[Mello] call_logger.close failed: {exc}", flush=True)
        await task.cancel()

    await PipelineRunner(handle_sigint=runner_args.handle_sigint).run(task)


if __name__ == "__main__":
    from app.config import settings

    # Print which database + LLM this process is wired to, so a stale process pointing at the
    # wrong DB (e.g. local SQLite while the dashboard reads Supabase) is obvious at a glance.
    _db = settings.database_url
    _target = "local SQLite (mello_dev.db)" if _db.startswith("sqlite") else _db.split("@")[-1]
    print(f"[Mello] LLM = {settings.llm_provider} ({settings.cerebras_model})")
    print(f"[Mello] DB  = {_target}")
    if _target.startswith("local"):
        print("[Mello] WARNING: writing to local SQLite — the Supabase dashboard will NOT see these bookings.")

    from pipecat.runner.run import main

    main()
