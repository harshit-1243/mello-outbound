"""Live probe of the production TTS (ElevenLabs Flash v2.5) and STT (Deepgram Nova-3 multi).

1. TTS: synthesize three short receptionist lines (English / Hinglish-Latin / Devanagari)
   with the configured voice; measure time-to-first-byte (streaming) and total time.
2. STT round-trip: feed the synthesized audio back through Deepgram nova-3 language=multi
   and compare transcripts — a proxy for how well the stack hears its own demographic.

Usage is tiny: ~260 TTS characters, ~20s of STT audio.
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import json
import time
from pathlib import Path

import httpx

from app.config import settings

OUT = Path(__file__).parent / "audit_audio"
OUT.mkdir(exist_ok=True)

SAMPLES = {
    "english": "Your football booking for tomorrow at seven pm is confirmed. That's twelve hundred rupees.",
    "hinglish": "Aapki booking confirm ho gayi hai. Kal shaam saat baje, football turf, barah sau rupaye.",
    "devanagari": "आपकी बुकिंग कन्फर्म हो गयी है। कल शाम सात बजे, फुटबॉल टर्फ।",
}


def tts_probe(name: str, text: str) -> Path | None:
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}/stream"
        f"?output_format=mp3_22050_32"
    )
    headers = {"xi-api-key": settings.elevenlabs_api_key, "Content-Type": "application/json"}
    body = {"text": text, "model_id": settings.elevenlabs_model}
    t0 = time.perf_counter()
    ttfb = None
    chunks = []
    try:
        with httpx.stream("POST", url, headers=headers, json=body, timeout=30) as r:
            if r.status_code != 200:
                r.read()
                print(f"  [{name}] TTS HTTP {r.status_code}: {r.text[:200]}")
                return None
            for chunk in r.iter_bytes():
                if ttfb is None:
                    ttfb = (time.perf_counter() - t0) * 1000
                chunks.append(chunk)
    except Exception as exc:  # noqa: BLE001
        print(f"  [{name}] TTS ERROR: {type(exc).__name__}: {str(exc)[:200]}")
        return None
    total = (time.perf_counter() - t0) * 1000
    audio = b"".join(chunks)
    path = OUT / f"{name}.mp3"
    path.write_bytes(audio)
    print(f"  [{name}] ttfb={ttfb:.0f}ms total={total:.0f}ms bytes={len(audio)} ({len(text)} chars)")
    return path


def stt_probe(name: str, path: Path, original: str) -> None:
    url = "https://api.deepgram.com/v1/listen?model=nova-3&language=multi&smart_format=true"
    headers = {"Authorization": f"Token {settings.deepgram_api_key}", "Content-Type": "audio/mpeg"}
    t0 = time.perf_counter()
    try:
        r = httpx.post(url, headers=headers, content=path.read_bytes(), timeout=60)
    except Exception as exc:  # noqa: BLE001
        print(f"  [{name}] STT ERROR: {type(exc).__name__}: {str(exc)[:200]}")
        return
    ms = (time.perf_counter() - t0) * 1000
    if r.status_code != 200:
        print(f"  [{name}] STT HTTP {r.status_code}: {r.text[:200]}")
        return
    data = r.json()
    alt = data["results"]["channels"][0]["alternatives"][0]
    print(f"  [{name}] {ms:.0f}ms confidence={alt.get('confidence', 0):.2f}")
    print(f"      said : {original}")
    print(f"      heard: {alt['transcript']}")


def main() -> None:
    print(f"TTS = ElevenLabs {settings.elevenlabs_model} voice={settings.elevenlabs_voice_id}")
    paths: dict[str, Path] = {}
    for name, text in SAMPLES.items():
        p = tts_probe(name, text)
        if p:
            paths[name] = p
        time.sleep(1)

    print("\nSTT = Deepgram nova-3 language=multi (round-trip of the TTS audio)")
    for name, p in paths.items():
        stt_probe(name, p, SAMPLES[name])
        time.sleep(1)


if __name__ == "__main__":
    main()
