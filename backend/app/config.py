"""Application settings, loaded from environment / .env file.

The booking engine defaults to a local SQLite database so it runs with zero configuration.
Set DATABASE_URL to a Supabase Postgres URI for production.
"""
from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database — SQLite by default; Postgres (Supabase) in production.
    database_url: str = "sqlite:///./mello_dev.db"

    # Mirror live outbound outcomes into the shared Supabase project (same one the inbound agent +
    # dashboard use), so a real call to a verified number shows on the dashboard. Best-effort: if
    # these are blank the agent just runs SQLite-only. Writes go to the outbound_* tables via REST.
    supabase_url: str = ""
    supabase_service_key: str = ""
    outbound_facility_id: str = "raheja-ileseum"

    # Comma-separated origins allowed to call the REST API from a browser. Add the deployed
    # dashboard's URL (e.g. https://mello-dashboard.vercel.app) in production .env.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # REST API key sent in X-API-Key header (or Authorization: Bearer <key>).
    # Leave blank in local dev — auth is skipped when this is empty.
    # Generate a strong key for production: python -c "import secrets; print(secrets.token_hex(32))"
    api_key: str = ""

    # --- Outbound (Mello Outbound) compliance ---
    # The dial gate is non-negotiable. dlt_registered MUST be True before any REAL dial happens
    # (TRAI / TCCCPR — sending entity, headers, and templates registered on DLT).
    outbound_dlt_registered: bool = False
    outbound_daily_cap: int = 1  # max attempts per contact per local calendar day

    # --- Twilio real test call (trial: call ONLY your verified number) ---
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""      # your Twilio (trial) number, E.164 e.g. +1XXXXXXXXXX
    public_base_url: str = ""         # your public https tunnel (ngrok), e.g. https://ab12.ngrok-free.app
    # HARD SAFETY: the /test-call endpoint may dial ONLY numbers in this list (your verified mobile).
    outbound_test_numbers: str = ""   # comma-separated E.164, e.g. +9198XXXXXXXX

    # LLM provider selection: "cerebras" (1M tok/day free, fastest), "google" (free Gemini),
    # "anthropic" (Claude), "groq"
    llm_provider: str = "google"

    # Google Gemini (default LLM — free tier, no card)
    google_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"  # higher free-tier daily quota + lower latency than flash

    # Anthropic / Claude (swap-in)
    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-4-5"

    # Groq (swap-in — free tier, low 100K tokens/day cap)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # Cerebras (swap-in — 1M tokens/day free, fastest inference; 8K context cap on free tier)
    cerebras_api_key: str = ""
    # Models available on this account: "zai-glm-4.7" (natural Hinglish — default) and
    # "gpt-oss-120b" (English-leaning, also strong tool-calling). Both verified for tool use.
    cerebras_model: str = "zai-glm-4.7"
    # Reasoning depth. "low" keeps voice turns ~1.5s. CRITICAL for gpt-oss-120b, whose default
    # ("medium") makes each turn ~20s. Harmless for zai-glm. Set "" to omit the parameter.
    cerebras_reasoning_effort: str = "low"

    # STT provider selection. Project stack is "sarvam" (set this once SARVAM_API_KEY is in .env);
    # "deepgram" is the interim until the Sarvam key lands.
    stt_provider: str = "sarvam"

    # Deepgram STT (interim STT until Sarvam key is configured)
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    deepgram_language: str = "multi"  # "multi" = Hindi/English code-switching; "en" for English-only

    # TTS provider selection. Project stack is "sarvam" (India-native Hinglish, bulbul:v2).
    # Requires SARVAM_API_KEY. "deepgram"/"elevenlabs" exist only as interim until the key lands.
    tts_provider: str = "sarvam"

    # Sarvam — India-native STT + TTS (+ optional LLM via the OpenAI-compatible endpoint).
    sarvam_api_key: str = ""
    # Sarvam LLM (set LLM_PROVIDER=sarvam): India-hosted, OpenAI-compatible chat with tool-calling.
    sarvam_base_url: str = "https://api.sarvam.ai/v1"
    sarvam_llm_model: str = "sarvam-105b"  # available: sarvam-30b (faster) | sarvam-105b (stronger)
    # STT: saarika:v2.5 is the streaming ASR that PRESERVES Hinglish. (Do not use saaras:* — those
    # translate speech to English, which would strip the Hindi the agent needs to reply in.)
    sarvam_stt_model: str = "saarika:v2.5"
    # TTS: bulbul:v2 is the "Standard" model — the balanced pick. bulbul:v3 is the pricier
    # "Advanced" tier; bulbul:v1 is older. Voice "anushka" is a female Hinglish speaker.
    sarvam_tts_model: str = "bulbul:v3"   # Advanced tier — clearer voice than v2
    sarvam_voice_id: str = "ritu"         # v3-compatible female voice (anushka is v2-only)
    sarvam_language: str = "hi-IN"   # TTS voice language (Hindi target with English code-mixing)
    # STT language (Sarvam requires a specific code — no auto-detect). "en-IN" transcribes English
    # correctly (the demo is English-first); switch to "hi-IN" if the caller mainly speaks Hindi.
    sarvam_stt_language: str = "en-IN"

    # ElevenLabs (TTS)
    elevenlabs_api_key: str = ""
    elevenlabs_model: str = "eleven_flash_v2_5"
    elevenlabs_voice_id: str = "EXAVITQu4vr4xnSDxMaL"  # "Sarah" — usable on the free tier

    # Deepgram Aura (cheaper TTS swap)
    deepgram_tts_model: str = "aura-2-thalia-en"

    # Exotel (M3)
    exotel_sid: str = ""
    exotel_api_key: str = ""
    exotel_api_token: str = ""
    exotel_subdomain: str = ""

    # WhatsApp BSP (M4)
    whatsapp_provider: str = "interakt"
    whatsapp_api_key: str = ""
    whatsapp_base_url: str = ""

    # --- Free-credit / usage monitor (app/voice/usage.py) ---
    # Daily free-tier ceilings used to gauge how close you are to running out. 0 = "unknown / don't
    # track a %" (the monitor still raises a hard alert when a provider returns a quota/credit error).
    # Set these to your actual free-tier allowances to get the proactive 80%/100% warnings.
    cerebras_daily_token_limit: int = 1_000_000   # Cerebras free tier ≈ 1M tokens/day
    sarvam_daily_char_limit: int = 0              # Sarvam TTS characters/day (set to your allowance)
    sarvam_daily_stt_seconds_limit: int = 0       # Sarvam STT seconds/day (set to your allowance)
    usage_warn_ratio: float = 0.8                 # warn once usage crosses 80% of a known limit

    @field_validator("database_url")
    @classmethod
    def _fallback_sqlite(cls, v: str) -> str:
        # A blank DATABASE_URL (e.g. the empty line in .env) means "use local SQLite",
        # not an invalid empty URL.
        return v or "sqlite:///./mello_dev.db"


settings = Settings()
