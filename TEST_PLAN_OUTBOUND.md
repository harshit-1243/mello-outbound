# Outbound Agent — Test Plan

Scope: the full outbound calling system in `backend/app/voice/` — the compliance dial-gate,
progressive dialer, answering-machine policy, disposition/retry engine, and the goal-driven
conversation brain across all 7 objectives. The deterministic practice-mode brain
(`conversation.py`) lets us exercise the *entire* agent decision surface with **zero API calls**,
so every case below runs in CI on SQLite.

How to run:

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_outbound_*.py -q      # whole outbound suite
.venv/Scripts/python.exe -m pytest tests/test_outbound_agent_flows.py -q   # the agent-flow cases below
```

Live smoke test (real Twilio call to the allowlisted number, manual):

```bash
curl -X POST http://localhost:8000/clients/1/test-call \
  -H "Content-Type: application/json" -d '{"to":"+918369851507","campaign_id":1}'
```

---

## 1. Compliance dial-gate — `test_outbound_compliance.py`

The gate runs before **every** dial; a contact is eligible only if ALL checks pass. Deny-first.

| # | Case | Expected | Status |
|---|---|---|---|
| 1.1 | All checks pass, inside window | `eligible` | ✅ existing |
| 1.2 | Now is after the calling window closes | block `outside_window` | ✅ existing |
| 1.3 | Now is before the window opens | block `outside_window` | ✅ existing |
| 1.4 | Contact on per-contact DNC / OptOut list | block `opted_out` | ✅ existing |
| 1.5 | No lawful consent basis | block `no_consent` | ✅ existing |
| 1.6 | Attempt count ≥ max_attempts | block `max_attempts` | ✅ existing |
| 1.7 | Attempts today ≥ daily cap | block `daily_cap` | ✅ existing |
| 1.8 | DLT/registration flag off | block `dlt_unregistered` | ✅ existing |
| 1.9 | Contact not in `pending` state | block `not_pending` | ✅ existing |
| 1.10 | Opt-out match across phone formats (bare/0-prefixed/+91) | block `opted_out` | ✅ existing |

## 2. Answering-machine detection — `test_outbound_amd.py`

Hard rule: a machine **never** reaches the bot.

| # | Case | Expected | Status |
|---|---|---|---|
| 2.1 | Carrier label → amd_result mapping (human/machine_*/fax/unknown) | correct class | ✅ existing |
| 2.2 | Human answer | action `converse` | ✅ existing |
| 2.3 | Voicemail, under cap | `leave_voicemail` once, then hang up | ✅ existing |
| 2.4 | IVR / unknown | `hang_up`, disposition `failed` | ✅ existing |
| 2.5 | End-to-end: voicemail never conversed with | no bot turn | ✅ existing |

## 3. Disposition & retry engine — `test_outbound_dispositions.py`

| # | Case | Expected | Status |
|---|---|---|---|
| 3.1 | Confirmed (terminal, success) | done + fires confirmation | ✅ existing |
| 3.2 | Refused (terminal) | done, no confirmation | ✅ existing |
| 3.3 | No-answer | schedules backoff, pending | ✅ existing |
| 3.4 | Busy + per-campaign override | short backoff applied | ✅ existing |
| 3.5 | Attempt ≥ max | `exhausted` | ✅ existing |
| 3.6 | Voicemail beyond its own cap | `exhausted` | ✅ existing |

## 4. Progressive dialer — `test_outbound_dialer.py`

| # | Case | Expected | Status |
|---|---|---|---|
| 4.1 | Eligible contact dialed | one call placed | ✅ existing |
| 4.2 | Opted-out contact | skipped | ✅ existing |
| 4.3 | Outside window | blocked, left pending | ✅ existing |
| 4.4 | Budget cap reached | stops dialing | ✅ existing |
| 4.5 | No-answer → retry → exhaust | progression correct | ✅ existing |
| 4.6 | Progressive: distinct contacts, one at a time | no double-dial | ✅ existing |

## 5. Objectives & openings — `test_outbound_objectives.py`

| # | Case | Expected | Status |
|---|---|---|---|
| 5.1 | Catalogue covers ≥5 objectives across sectors | labels + sectors present | ✅ existing |
| 5.2 | Opening is English-first, names the business, asks a y/n, no upfront AI claim | per objective | ✅ existing |
| 5.3 | Generic "yes" | `confirmed` | ✅ existing |
| 5.4 | Generic "no" | `refused` | ✅ existing |
| 5.5 | Every objective honors opt-out | `opt_out` + DNC set | ✅ existing |

## 6. Conversation brain — core tools & flows — `test_outbound_bot.py`

| # | Case | Expected | Status |
|---|---|---|---|
| 6.1 | confirm / cancel / reschedule / opt-out tools | correct disposition + DB effect | ✅ existing |
| 6.2 | Scripted confirm (Hinglish) | `confirmed` | ✅ existing |
| 6.3 | Scripted opt-out persists DNC + OptOut row | `opt_out` | ✅ existing |
| 6.4 | Busy → callback | `callback_requested` | ✅ existing |
| 6.5 | "Are you a robot?" → discloses, then confirms | disclosed honestly | ✅ existing |
| 6.6 | Wrong number | `wrong_number` | ✅ existing |
| 6.7 | Unparseable reschedule → callback fallback | `callback_requested` | ✅ existing |

## 7. Conversation brain — edge & robustness — `test_outbound_agent_flows.py` (NEW)

These close the gaps not previously asserted: the reschedule happy path through a full scripted
turn, silence/garbled-input exhaustion, intent-priority precedence, Devanagari intent matching,
and the slot-unavailable retry prompt.

| # | Case | Expected | Status |
|---|---|---|---|
| 7.1 | Scripted reschedule with a parseable date+time | `rescheduled`, booking moved | 🆕 new |
| 7.2 | Reschedule onto an occupied slot | tool returns not-ok + "koi aur time" reprompt | 🆕 new |
| 7.3 | Explicit "no" in booking confirmation | cancels → `refused` | 🆕 new |
| 7.4 | Two silent turns | `callback_requested` | 🆕 new |
| 7.5 | Three unintelligible turns | `callback_requested` | 🆕 new |
| 7.6 | Devanagari opt-out (`बंद करो`) | `opt_out` + DNC set | 🆕 new |
| 7.7 | Devanagari wrong number (`गलत नंबर`) | `wrong_number` | 🆕 new |
| 7.8 | Mixed intent "stop calling, wrong number" | opt-out wins (checked first) | 🆕 new |
| 7.9 | Generic objective "are you AI?" disclosure | says "automated", call continues | 🆕 new |

## 7b. Prompt↔tool wiring per objective — `test_outbound_tool_coverage.py` (NEW)

Regression guard for the bug where non-booking objectives' prompts named tools (`mark_renewal`,
`log_interest`, `record_feedback`, `decline`) that were never registered with the LLM — so a live
renewal/promo/feedback call could not complete. Fix: per-objective tool schemas in
`outbound_pipeline_tools.py`.

| # | Case | Expected | Status |
|---|---|---|---|
| 7b.1 | Every tool named in an objective's prompt is in its LLM schema | all 7 objectives | 🆕 new |
| 7b.2 | Every schema tool has a dispatch handler | all 7 objectives | 🆕 new |
| 7b.3 | Renewal/reactivation/promo/feedback expose their affirmative tool | present | 🆕 new |

## 7c. Per-objective LLM drive (Cerebras) — `bench_objectives_llm.py` (NEW, manual)

Sends each objective its real prompt + real schema, plays an affirmative line, asserts the right
completion tool fires, and times it. Result: **7/7 objectives call the correct tool**; clean TTFT
412–547 ms for short objectives, ~2.8 s for booking (longer prompt), median ~435 ms.

## 8. Live telephony smoke (manual, not in CI)

| # | Case | Expected |
|---|---|---|
| 8.1 | `/test-call` to allowlisted number | Twilio SID returned, phone rings, bot opens |
| 8.2 | `/test-call` to a non-allowlisted number | HTTP 403 (`outbound_test_numbers` guard) |
| 8.3 | `/test-call` with Twilio creds missing | HTTP 400 (`Twilio not configured`) |

---

### Guardrails noted but not separately asserted
- `MAX_TURNS` (6) is a defensive backstop; the sub-caps (empty ≥2, unknown ≥3, reschedule
  retries ≥2) terminate every reachable path first, so it is covered transitively.
