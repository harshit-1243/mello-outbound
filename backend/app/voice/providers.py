"""Swappable STT / LLM / TTS factories driven by config.

Every provider is constructed here so the rest of the pipeline never imports a specific vendor.
Switch providers by changing LLM_PROVIDER / TTS_PROVIDER in .env — no code changes. Imports are
lazy so you only need the SDK for the provider you actually select.
"""
from __future__ import annotations

from app.config import settings


def make_stt():
    """Speech-to-text. Project stack is Sarvam (set STT_PROVIDER=sarvam once SARVAM_API_KEY exists).
    Deepgram Nova-3 (language='multi') remains selectable as the interim until the Sarvam key lands."""
    provider = settings.stt_provider.lower()

    if provider == "sarvam":
        if not settings.sarvam_api_key:
            raise RuntimeError(
                "STT_PROVIDER=sarvam but SARVAM_API_KEY is empty. Add the key to backend/.env "
                "(Sarvam is the project's chosen STT/TTS provider), or temporarily set "
                "STT_PROVIDER=deepgram to keep testing."
            )
        from pipecat.services.sarvam.stt import SarvamSTTService

        return SarvamSTTService(
            api_key=settings.sarvam_api_key,
            model=settings.sarvam_stt_model,  # saarika:v2.5 — ASR (NOT saaras, which translates)
            params=SarvamSTTService.InputParams(language=settings.sarvam_stt_language),
        )

    if provider == "deepgram":
        from pipecat.services.deepgram.stt import DeepgramSTTService, LiveOptions

        return DeepgramSTTService(
            api_key=settings.deepgram_api_key,
            live_options=LiveOptions(
                model=settings.deepgram_model,
                language=settings.deepgram_language,
                smart_format=True,
                # NOTE: do NOT add `keywords=[...]` here. Nova-3 rejects the legacy `keywords`
                # parameter (replaced by keyterm prompting, which is English-only and incompatible
                # with language="multi"). Sending it kills the STT websocket. Name accuracy is
                # handled at the prompt level (clarify-on-uncertainty + spell the name back).
                #
                # Wait 500 ms of silence before finalising — the default (10 ms) splits a sentence
                # into fragments.
                endpointing=500,
            ),
        )

    raise ValueError(f"Unknown STT_PROVIDER: {settings.stt_provider!r} (use sarvam|deepgram)")


def make_llm():
    """LLM for reasoning + booking tool calls. Default: free Google Gemini."""
    provider = settings.llm_provider.lower()
    if provider == "google":
        from pipecat.services.google.llm import GoogleLLMService

        return GoogleLLMService(api_key=settings.google_api_key, model=settings.gemini_model)
    if provider == "anthropic":
        from pipecat.services.anthropic.llm import AnthropicLLMService

        return AnthropicLLMService(api_key=settings.anthropic_api_key, model=settings.claude_model)
    if provider == "groq":
        from pipecat.services.groq.llm import GroqLLMService

        return GroqLLMService(api_key=settings.groq_api_key, model=settings.groq_model)
    if provider == "sarvam":
        if not settings.sarvam_api_key:
            raise RuntimeError("LLM_PROVIDER=sarvam but SARVAM_API_KEY is empty. Add it to backend/.env.")
        # Sarvam's chat API is OpenAI-compatible (incl. tool-calling) and India-hosted — lower
        # round-trip than US providers for India calls. Use the generic OpenAI service + base_url.
        from pipecat.services.openai.llm import OpenAILLMService

        return OpenAILLMService(
            api_key=settings.sarvam_api_key,
            base_url=settings.sarvam_base_url,
            model=settings.sarvam_llm_model,
        )
    if provider == "cerebras":
        from pipecat.services.cerebras.llm import CerebrasLLMService

        # reasoning_effort is passed through to the API via `extra`. "low" keeps turns ~1.5s
        # and, crucially, stops gpt-oss-120b from defaulting to its ~20s "medium" reasoning.
        extra = {}
        if settings.cerebras_reasoning_effort:
            extra["reasoning_effort"] = settings.cerebras_reasoning_effort
        # retry_timeout_secs wraps each completion in asyncio.wait_for; retry_on_timeout retries
        # once instead of hanging silently. Without these, a slow/stuck Cerebras turn produces dead
        # air on the call (the caller hears nothing and says "Hello?"). See on_completion_timeout
        # in bot.py, which speaks a short filler if a turn still times out.
        return CerebrasLLMService(
            api_key=settings.cerebras_api_key,
            settings=CerebrasLLMService.Settings(model=settings.cerebras_model, extra=extra),
            retry_timeout_secs=6.0,
            retry_on_timeout=True,
        )
    raise ValueError(
        f"Unknown LLM_PROVIDER: {settings.llm_provider!r} (use sarvam|cerebras|google|anthropic|groq)"
    )


def make_tts():
    """TTS voice. Production decision: Sarvam bulbul (India-native Hinglish, cheapest).
    ElevenLabs Flash v2.5 is the active default until a Sarvam key is configured."""
    provider = settings.tts_provider.lower()
    if provider == "sarvam":
        if not settings.sarvam_api_key:
            raise RuntimeError(
                "TTS_PROVIDER=sarvam but SARVAM_API_KEY is empty. Add the key to backend/.env "
                "(Sarvam bulbul is the project's chosen Hinglish voice), or temporarily set "
                "TTS_PROVIDER=deepgram to keep testing."
            )
        from pipecat.services.sarvam.tts import SarvamTTSService

        return SarvamTTSService(
            api_key=settings.sarvam_api_key,
            model=settings.sarvam_tts_model,
            voice_id=settings.sarvam_voice_id,
            params=SarvamTTSService.InputParams(language=settings.sarvam_language),
        )
    if provider == "elevenlabs":
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

        return ElevenLabsTTSService(
            api_key=settings.elevenlabs_api_key,
            voice_id=settings.elevenlabs_voice_id,
            model=settings.elevenlabs_model,
        )
    if provider == "deepgram":
        from pipecat.services.deepgram.tts import DeepgramTTSService

        return DeepgramTTSService(api_key=settings.deepgram_api_key, voice=settings.deepgram_tts_model)
    raise ValueError(f"Unknown TTS_PROVIDER: {settings.tts_provider!r} (use elevenlabs|deepgram)")
