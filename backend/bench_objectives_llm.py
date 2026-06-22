"""Per-objective LLM correctness + latency across all outbound call types.

For each of the 7 objectives (booking, renewal, reactivation, lead-qual, no-show, promo, feedback)
this sends Cerebras the objective's REAL system prompt + REAL tool schema, plays one affirmative
caller line, and checks the model calls the expected completion tool — and times it. Proves the
tool-wiring fix end-to-end (each campaign type now drives its own tool) and reports latency by type.

Run:  cd backend && .venv/Scripts/python.exe bench_objectives_llm.py
"""
from __future__ import annotations

import datetime as dt
import json
import time

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

from app.config import settings
from app.db.models import (
    OBJECTIVE_BOOKING_CONFIRMATION,
    OBJECTIVE_FEEDBACK,
    OBJECTIVE_LEAD_QUALIFICATION,
    OBJECTIVE_MEMBERSHIP_RENEWAL,
    OBJECTIVE_NO_SHOW_FOLLOWUP,
    OBJECTIVE_PROMO_OFFER,
    OBJECTIVE_REACTIVATION,
)
from app.voice.outbound_pipeline_tools import build_outbound_tools_schema
from app.voice.outbound_prompts import build_outbound_system_prompt

CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
BUSINESS = "Smash Arena"
_RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError)
PACE = 3.0

# objective -> (affirmative caller line, expected tool, context)
CASES = {
    OBJECTIVE_BOOKING_CONFIRMATION: ("Haan ji, booking bilkul theek hai.", "confirm_booking",
                                     {"service": "Badminton", "when": "kal shaam"}),
    OBJECTIVE_MEMBERSHIP_RENEWAL: ("Haan, membership renew kar do please.", "mark_renewal",
                                   {"service": "gym membership", "when": ""}),
    OBJECTIVE_REACTIVATION: ("Haan, agli visit book karni hai.", "log_interest",
                             {"service": "haircut", "when": ""}),
    OBJECTIVE_LEAD_QUALIFICATION: ("Haan, mujhe interest hai, batao.", "log_interest",
                                   {"service": "personal training", "when": ""}),
    OBJECTIVE_NO_SHOW_FOLLOWUP: ("Haan, rebook kar do please.", "log_interest",
                                 {"service": "dental checkup", "when": "kal"}),
    OBJECTIVE_PROMO_OFFER: ("Haan, offer ke baare mein batao.", "log_interest",
                            {"service": "spa package", "when": ""}),
    OBJECTIVE_FEEDBACK: ("Service bahut acchi thi, main khush hoon.", "record_feedback",
                         {"service": "salon visit", "when": ""}),
}


def _tools_for(objective: str) -> list[dict]:
    return [
        {"type": "function", "function": {
            "name": s.name, "description": s.description,
            "parameters": {"type": "object", "properties": s.properties, "required": s.required},
        }}
        for s in build_outbound_tools_schema(objective).standard_tools
    ]


def _call(client: OpenAI, system: str, user: str, tools: list[dict]) -> tuple[float, float, list[str]]:
    extra = {"reasoning_effort": settings.cerebras_reasoning_effort} if settings.cerebras_reasoning_effort else {}
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    time.sleep(PACE)
    for attempt in range(6):
        try:
            start = time.perf_counter()
            stream = client.chat.completions.create(
                model=settings.cerebras_model, messages=messages, tools=tools,
                stream=True, temperature=0.2, extra_body=extra,
            )
            break
        except _RETRYABLE as e:
            wait = 2 ** attempt
            print(f"    (retry {attempt + 1}: {type(e).__name__} — {wait}s)")
            time.sleep(wait)
    else:
        return -1.0, -1.0, ["<rate-limited>"]
    ttft = None
    calls: dict[int, str] = {}
    for chunk in stream:
        if ttft is None:
            ttft = (time.perf_counter() - start) * 1000
        for tc in (chunk.choices[0].delta.tool_calls or []):
            if tc.function and tc.function.name:
                calls[tc.index] = calls.get(tc.index, "") + tc.function.name
    full = (time.perf_counter() - start) * 1000
    return ttft or full, full, list(calls.values())


def main() -> None:
    if not settings.cerebras_api_key:
        raise SystemExit("CEREBRAS_API_KEY empty in backend/.env.")
    client = OpenAI(api_key=settings.cerebras_api_key, base_url=CEREBRAS_BASE_URL, timeout=30.0, max_retries=0)
    today = dt.date(2030, 7, 2)
    print(f"Model: {settings.cerebras_model} | reasoning_effort={settings.cerebras_reasoning_effort or 'default'}\n")
    print(f"{'objective':<24}{'TTFT ms':>9}{'full ms':>9}  {'expected':<16}{'got':<18}{'ok'}")
    print("-" * 86)
    results = []
    for obj, (line, expected, ctx) in CASES.items():
        system = build_outbound_system_prompt(obj, BUSINESS, today, ctx)
        ttft, full, got = _call(client, system, line, _tools_for(obj))
        ok = expected in got
        results.append((obj, ttft, full, ok))
        print(f"{obj:<24}{ttft:>9.0f}{full:>9.0f}  {expected:<16}{(','.join(got) or '<none>'):<18}{'PASS' if ok else 'FAIL'}")
    print("-" * 86)
    oks = [r for r in results if r[3]]
    clean = [r[1] for r in results if r[1] > 0]
    print(f"Correct tool: {len(oks)}/{len(results)} objectives", end="")
    if clean:
        print(f" | TTFT min {min(clean):.0f} / median {sorted(clean)[len(clean)//2]:.0f} / max {max(clean):.0f} ms")
    else:
        print(" | (no clean latency samples — free tier congested)")


if __name__ == "__main__":
    main()
