"""Audio smoke test — needs ONLY your TTS key (ElevenLabs/Deepgram), no LLM or STT.

Run it now to confirm your browser audio + WebRTC + text-to-speech all work, before you have the
Gemini key:

    python -m app.voice.check_audio

Open the printed URL (default http://localhost:7860), click Connect, and you should hear Mello
greet you. If you do, the audio path is good and the full agent (app.voice.bot) just needs the
free GOOGLE_API_KEY added to .env.
"""
from __future__ import annotations

import sys

# Force UTF-8 stdout so Pipecat's dev runner (which prints an emoji) starts on Windows consoles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import TransportParams

from app.voice.providers import make_tts

transport_params = {
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        vad_analyzer=SileroVADAnalyzer(),
    ),
}


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(runner_args, transport_params)
    tts = make_tts()

    pipeline = Pipeline([transport.input(), tts, transport.output()])
    task = PipelineTask(pipeline)

    @transport.event_handler("on_client_connected")
    async def _on_connected(_transport, _client):
        await task.queue_frames(
            [
                TTSSpeakFrame(
                    "Namaste! This is Mello, your A-I receptionist. "
                    "If you can hear me clearly, your audio and text to speech are working perfectly."
                )
            ]
        )

    await PipelineRunner(handle_sigint=runner_args.handle_sigint).run(task)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
