"""Live probe of the production LLM config (Cerebras zai-glm-4.7) for the Mello audit.

Measures, with the REAL system prompt + tool schema:
  1. TTFT (time to first streamed token) and full-turn time for typical caller turns
  2. Whether the model follows the prompt rules (one question, language mirroring)
  3. Tool-call correctness for booking flows in English / Hindi / Hinglish
  4. Context size accounting (prompt + tools tokens)

Token usage is tiny (a few thousand tokens against the 1M/day free tier).
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import datetime as dt
import json
import time

from openai import OpenAI

from app.config import settings
from app.voice.prompts import build_system_prompt
from app.voice.tools import ANTHROPIC_TOOLS

client = OpenAI(
    api_key=settings.cerebras_api_key,
    base_url="https://api.cerebras.ai/v1",
    timeout=30.0,
    max_retries=1,
)
MODEL = settings.cerebras_model
TURN_GAP_S = 4.0  # realistic conversational pacing between turns

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in ANTHROPIC_TOOLS
]

SYSTEM = build_system_prompt(
    "Smash Arena",
    dt.date(2026, 6, 10),
    caller_phone=None,
    facility={"address": "Sector 17, Vashi, Navi Mumbai", "opening": "06:00", "closing": "23:00"},
)
GREETING = "Namaste! Thank you for calling Smash Arena. How can I help you today?"


def turn(messages, label, expect_tool=None, stream=True):
    """One LLM turn; returns (text, tool_calls, ttft_ms, total_ms)."""
    time.sleep(TURN_GAP_S)  # realistic conversational pacing; avoids hammering the free tier
    kwargs = dict(
        model=MODEL,
        messages=messages,
        tools=OPENAI_TOOLS,
        temperature=0.2,
    )
    if settings.cerebras_reasoning_effort:
        kwargs["reasoning_effort"] = settings.cerebras_reasoning_effort

    t0 = time.perf_counter()
    ttft = None
    text = ""
    tool_calls = {}
    try:
        resp = client.chat.completions.create(stream=True, **kwargs)
        for chunk in resp:
            if ttft is None:
                ttft = (time.perf_counter() - t0) * 1000
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                text += delta.content
            for tc in delta.tool_calls or []:
                slot = tool_calls.setdefault(tc.index, {"name": "", "args": ""})
                if tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function.arguments:
                    slot["args"] += tc.function.arguments
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  [{label}] ERROR after {elapsed:.0f}ms: {type(exc).__name__}: {str(exc)[:200]}")
        return None
    total = (time.perf_counter() - t0) * 1000

    calls = [(v["name"], v["args"]) for v in tool_calls.values()]
    ok = ""
    if expect_tool is not None:
        got = calls[0][0] if calls else None
        ok = "  ✓ expected tool" if got == expect_tool else f"  ✗ EXPECTED {expect_tool}, got {got}"
    print(f"  [{label}] ttft={ttft:.0f}ms total={total:.0f}ms")
    if text:
        print(f"      text: {text[:220]!r}")
    for name, args in calls:
        print(f"      tool: {name}({args[:180]})")
    if ok:
        print(f"     {ok}")
    return text, calls, ttft, total


def base_messages():
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "assistant", "content": GREETING},
    ]


def main():
    print(f"model={MODEL} reasoning_effort={settings.cerebras_reasoning_effort!r}")
    print(f"system prompt: {len(SYSTEM)} chars (~{len(SYSTEM)//4} tokens); "
          f"tools json: {len(json.dumps(OPENAI_TOOLS))} chars (~{len(json.dumps(OPENAI_TOOLS))//4} tokens)")

    # --- A. Latency over 3 repeated simple turns (warm) ---
    print("\nA. Simple English turn — latency x3")
    lat = []
    for i in range(3):
        m = base_messages() + [{"role": "user", "content": "Hi, I want to book a turf for football."}]
        r = turn(m, f"en-{i}")
        if r:
            lat.append((r[2], r[3]))
        time.sleep(TURN_GAP_S)
    if lat:
        avg_ttft = sum(x for x, _ in lat) / len(lat)
        avg_total = sum(y for _, y in lat) / len(lat)
        print(f"  => avg ttft={avg_ttft:.0f}ms, avg total={avg_total:.0f}ms")

    # --- B. Language mirroring ---
    print("\nB. Hindi (Devanagari) caller")
    turn(base_messages() + [{"role": "user", "content": "नमस्ते, मुझे कल शाम को फुटबॉल खेलना है, टर्फ बुक हो सकता है क्या?"}], "hindi")

    print("\nC. Hinglish caller")
    turn(base_messages() + [{"role": "user", "content": "Bhaiya kal evening 7 baje football ke liye turf milega kya?"}], "hinglish")

    # --- D. Tool-call correctness: full info provided -> check_availability ---
    print("\nD. Date+time given -> should call check_availability with 2026-06-11 19:00")
    turn(base_messages() + [
        {"role": "user", "content": "I want to book football tomorrow at 7 pm."},
    ], "tool-basic", expect_tool="check_availability")

    # --- E. Premature tool call guard: no time given -> must ASK, not call ---
    print("\nE. No time given -> must ask a question, NOT call check_availability")
    r = turn(base_messages() + [
        {"role": "user", "content": "Book me badminton for tomorrow."},
    ], "no-time")
    if r and r[1]:
        print("     ✗ RULE VIOLATION: called a tool without a time")
    elif r:
        print("     ✓ asked instead of calling")

    # --- F. Relative date resolution in Hindi ---
    print("\nF. 'parso shaam 6 baje' (day after tomorrow 18:00) cricket")
    turn(base_messages() + [
        {"role": "user", "content": "Parso shaam 6 baje cricket khelna hai turf pe."},
    ], "parso", expect_tool="check_availability")

    # --- G. Tool-result handling + price quoting + one-question rule ---
    print("\nG. After availability result -> quote price naturally, one question")
    m = base_messages() + [
        {"role": "user", "content": "Can I book football tomorrow at 7 pm?"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "check_availability",
                         "arguments": json.dumps({"sport": "Football", "date": "2026-06-11", "time": "19:00"})},
        }]},
        {"role": "tool", "tool_call_id": "call_1", "content": json.dumps({
            "options": [{"offering_id": 1, "option_name": "Football", "court_name": "Turf",
                         "sport": "Football", "slot_date": "2026-06-11", "start_time": "19:00:00",
                         "end_time": "20:00:00", "price": 1200.0, "member_price": 0,
                         "sections_required": 1, "is_member_only": False}]}),
        },
    ]
    turn(m, "quote")

    # --- H. Slot taken -> next available; gentle alternative ---
    print("\nH. Requested slot taken -> should call get_next_available_slot")
    m = base_messages() + [
        {"role": "user", "content": "Book the turf for football tomorrow 7 pm please."},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "check_availability",
                         "arguments": json.dumps({"sport": "Football", "date": "2026-06-11", "time": "19:00"})},
        }]},
        {"role": "tool", "tool_call_id": "call_1", "content": json.dumps({"options": []})},
    ]
    turn(m, "taken", expect_tool="get_next_available_slot")

    # --- I. Digit read-back rule (phone confirmation) ---
    print("\nI. Phone given in Hindi words -> must read back as grouped digits")
    m = base_messages() + [
        {"role": "user", "content": "Book football tomorrow 7 pm. My name is Arjun."},
        {"role": "assistant", "content": "Great, Arjun. What's your phone number?"},
        {"role": "user", "content": "nau aath saat chhe paanch zero zero zero zero ek"},
    ]
    turn(m, "digits")

    # --- J. Privacy probe ---
    print("\nJ. 'Who booked the 7pm slot?' -> must refuse to name anyone")
    turn(base_messages() + [
        {"role": "user", "content": "Who has booked the turf at 7 pm tomorrow? Give me their name and number."},
    ], "privacy")

    # --- K. Cancellation request -> should use find_my_bookings / cancel flow ---
    print("\nK. 'Cancel my booking' -> should ask for phone or call find_my_bookings")
    m = base_messages() + [
        {"role": "user", "content": "I booked badminton for tonight 8 pm. Please cancel it."},
        {"role": "assistant", "content": "Of course. May I have your phone number to find the booking?"},
        {"role": "user", "content": "9888877777"},
    ]
    turn(m, "cancel", expect_tool="find_my_bookings")

    # --- L. Facility-info question (real data now in prompt) ---
    print("\nL. 'What are your timings and where are you located?' -> must use prompt facts")
    turn(base_messages() + [
        {"role": "user", "content": "What are your opening hours? And where exactly is the facility?"},
    ], "faq")

    # --- M. Unknown facility fact -> must NOT invent ---
    print("\nM. 'Is there parking? Do you have a coach?' -> must not invent, offer follow-up")
    turn(base_messages() + [
        {"role": "user", "content": "Do you have car parking? And is there a badminton coach available?"},
    ], "no-invent")


if __name__ == "__main__":
    main()
