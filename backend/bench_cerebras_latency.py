"""Cerebras LLM latency benchmark for the outbound agent.

Sends Cerebras the SAME system prompt (build_outbound_system_prompt) and the SAME tool schemas
(build_outbound_tools_schema) that a live outbound call uses, then replays caller turns and times
each completion. Reports time-to-first-token (TTFT — what the caller "feels" before the voice
starts) and full-completion time, across conversations of different LENGTHS (turn count) and
DEPTHS (shallow yes/no vs. tool-call-with-args round trips).

Run:  cd backend && .venv/Scripts/python.exe bench_cerebras_latency.py [--runs 3]
"""
from __future__ import annotations

import argparse
import datetime as dt
import statistics as stats
import time

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

_RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError)

from app.config import settings
from app.db.models import OBJECTIVE_BOOKING_CONFIRMATION
from app.voice.outbound_pipeline_tools import _SCHEMAS
from app.voice.outbound_prompts import build_outbound_system_prompt

CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
BUSINESS = "Smash Arena"
CTX = {"service": "Badminton", "when": "kal shaam", "booking_phone": "9876500001",
       "booking_date": "2030-07-03", "booking_time": "18:00"}


def _openai_tools() -> list[dict]:
    """Convert the production FunctionSchemas into OpenAI/Cerebras tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": s.name,
                "description": s.description,
                "parameters": {"type": "object", "properties": s.properties, "required": s.required},
            },
        }
        for s in _SCHEMAS
    ]


# Each scenario is a list of caller turns. A turn is (caller_text, tool_result_to_feed_back).
# tool_result is the canned result we return if the model calls a tool that turn (mimics our
# in-process tool handler), so the NEXT turn's latency includes the tool round-trip — that's "depth".
SCENARIOS = {
    # length 1, depth 1 — single direct confirmation
    "confirm (1 turn, shallow)": [
        ("Haan ji, bilkul theek hai.", {"ok": True, "message": "Confirmed.", "done": True}),
    ],
    # length 1, depth 1 — immediate opt-out (compliance-critical, must be fast)
    "opt-out (1 turn, shallow)": [
        ("Bhai mujhe call mat karo, stop calling.", {"ok": True, "message": "Removed.", "done": True}),
    ],
    # length 2, medium — one clarification then confirm
    "clarify+confirm (2 turns, medium)": [
        ("Kaun bol raha hai? Kya baat hai?", None),
        ("Achha haan, woh booking theek hai.", {"ok": True, "message": "Confirmed.", "done": True}),
    ],
    # length 3, deep — reschedule: ask, give date/time (tool call w/ args), tool result, wrap up
    "reschedule (3 turns, deep)": [
        ("Actually mujhe time change karna hai.", None),
        ("Kal ki jagah parso, shaam saat baje.", {"ok": True, "message": "Moved to 2030-07-04 19:00.", "done": False}),
        ("Haan perfect, thank you.", {"ok": True, "message": "Done.", "done": True}),
    ],
    # length 5, deep — chit-chat + AI question + reschedule with a correction, then confirm
    "long mixed (5 turns, deep)": [
        ("Hello? Kaun?", None),
        ("Ek minute, aap robot ho kya?", None),
        ("Theek hai. Mujhe booking aage badhani hai.", None),
        ("Parso shaam saat baje kar do.", {"ok": True, "message": "Moved to 2030-07-04 19:00.", "done": False}),
        ("Haan ho gaya, dhanyavaad.", {"ok": True, "message": "Done.", "done": True}),
    ],
}


def _client() -> OpenAI:
    if not settings.cerebras_api_key:
        raise SystemExit("CEREBRAS_API_KEY is empty in backend/.env — cannot benchmark.")
    return OpenAI(api_key=settings.cerebras_api_key, base_url=CEREBRAS_BASE_URL, timeout=30.0, max_retries=0)


PACE_SECONDS = 3.0  # gap between calls to stay under the Cerebras free-tier request rate


def _timed_completion(client: OpenAI, messages: list[dict], tools: list[dict]) -> tuple[float, float, object]:
    """Stream one completion. Returns (ttft_ms, full_ms, assistant_message). Retries on 429 with
    backoff; timing starts only on the successful attempt so backoff never inflates the numbers."""
    extra = {"reasoning_effort": settings.cerebras_reasoning_effort} if settings.cerebras_reasoning_effort else {}
    time.sleep(PACE_SECONDS)
    for attempt in range(6):
        try:
            start = time.perf_counter()
            stream = client.chat.completions.create(
                model=settings.cerebras_model, messages=messages, tools=tools,
                stream=True, temperature=0.3, extra_body=extra,
            )
            break
        except _RETRYABLE as e:
            wait = 2 ** attempt
            print(f"  (retry {attempt + 1}: {type(e).__name__} — backing off {wait}s)")
            time.sleep(wait)
    else:
        raise SystemExit("Cerebras kept failing after 6 retries — free tier congested; try again later.")
    ttft = None
    chunks_content, tool_calls = [], {}
    for chunk in stream:
        if ttft is None:
            ttft = (time.perf_counter() - start) * 1000
        delta = chunk.choices[0].delta
        if delta.content:
            chunks_content.append(delta.content)
        for tc in (delta.tool_calls or []):
            slot = tool_calls.setdefault(tc.index, {"id": tc.id, "name": "", "args": ""})
            if tc.id:
                slot["id"] = tc.id
            if tc.function and tc.function.name:
                slot["name"] += tc.function.name
            if tc.function and tc.function.arguments:
                slot["args"] += tc.function.arguments
    full = (time.perf_counter() - start) * 1000
    msg: dict = {"role": "assistant", "content": "".join(chunks_content) or None}
    if tool_calls:
        msg["tool_calls"] = [
            {"id": t["id"], "type": "function", "function": {"name": t["name"], "arguments": t["args"]}}
            for t in tool_calls.values()
        ]
    return ttft or full, full, msg


def run_scenario(client: OpenAI, name: str, turns: list, tools: list[dict]) -> list[dict]:
    system = build_outbound_system_prompt(OBJECTIVE_BOOKING_CONFIRMATION, BUSINESS, dt.date(2030, 7, 2), CTX)
    messages: list[dict] = [{"role": "system", "content": system}]
    per_turn = []
    for i, (caller_text, tool_result) in enumerate(turns, 1):
        messages.append({"role": "user", "content": caller_text})
        ttft, full, asst = _timed_completion(client, messages, tools)
        messages.append(asst)
        called = [tc["function"]["name"] for tc in asst.get("tool_calls", [])]
        # If the model called a tool, feed the canned tool result back (the round-trip adds to depth).
        if asst.get("tool_calls"):
            for tc in asst["tool_calls"]:
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": str(tool_result or {"ok": True})})
            ttft2, full2, asst2 = _timed_completion(client, messages, tools)
            messages.append(asst2)
            full += full2  # the turn's true latency includes the post-tool completion
        per_turn.append({"turn": i, "ttft_ms": ttft, "full_ms": full, "tool": ",".join(called) or "-"})
    return per_turn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2, help="repeats per scenario (median reported)")
    args = ap.parse_args()

    client = _client()
    tools = _openai_tools()
    print(f"Model: {settings.cerebras_model} | reasoning_effort={settings.cerebras_reasoning_effort or 'default'} "
          f"| endpoint={CEREBRAS_BASE_URL} | runs={args.runs}\n")

    all_full = []
    print(f"{'scenario':<34}{'turn':>5}{'TTFT ms':>10}{'turn ms':>10}{'tool':>20}")
    print("-" * 79)
    for name, turns in SCENARIOS.items():
        # median across runs, per turn
        runs = [run_scenario(client, name, turns, tools) for _ in range(args.runs)]
        for ti in range(len(turns)):
            ttfts = [r[ti]["ttft_ms"] for r in runs]
            fulls = [r[ti]["full_ms"] for r in runs]
            tool = runs[-1][ti]["tool"]
            all_full.extend(fulls)
            label = name if ti == 0 else ""
            print(f"{label:<34}{ti + 1:>5}{stats.median(ttfts):>10.0f}{stats.median(fulls):>10.0f}{tool:>20}")
        conv_ms = [sum(t["full_ms"] for t in r) for r in runs]
        print(f"{'  = full conversation':<34}{'':>5}{'':>10}{stats.median(conv_ms):>10.0f}{'':>20}")
        print()

    print("-" * 79)
    print(f"Across all turns:  median {stats.median(all_full):.0f} ms | "
          f"p95 {sorted(all_full)[max(0, int(len(all_full) * 0.95) - 1)]:.0f} ms | "
          f"max {max(all_full):.0f} ms")


if __name__ == "__main__":
    main()
