# Mello — Full-System Audit Findings
_Date: 2026-06-10 · Scope: booking engine, voice pipeline (STT/LLM/TTS), REST API, dashboard_

This audit read every source file, ran the existing 40-test suite, added 15 adversarial tests
(7 fail = 7 confirmed engine flaws), and ran **live probes** against the production providers
(Cerebras `zai-glm-4.7`, ElevenLabs Flash v2.5, Deepgram nova-3 multi) and the REST API.

Verification artifacts left in the repo:
- `backend/tests/test_adversarial_audit.py` — the failing tests document each engine flaw.
- `backend/audit_llm_probe.py` — live LLM latency / rule-following / tool-calling probe.
- `backend/audit_speech_probe.py` — TTS + STT round-trip probe (Hindi/Hinglish/English).
- `backend/audit_api_probe.py` — REST endpoint, error-path, CORS, and auth probe.

---

## Severity summary

| # | Severity | Area | Flaw | Evidence |
|---|----------|------|------|----------|
| 1 | **CRITICAL** | Engine | Phone not normalized at write → group rules & weekly cap silently bypassed for Exotel (+91) callers | failing test x2 |
| 2 | **CRITICAL** | API | No authentication; customer names+phones readable by anyone; any `client_id` enumerable | live probe |
| 3 | **HIGH** | API/Deploy | CORS allows only `localhost:3000`; deployed Vercel dashboard is blocked in production | live preflight = 400 |
| 4 | **HIGH** | Voice | `check_availability` with no time returns ~3,300 tokens; overflows 8K Cerebras context mid-call | live probe (51 options) |
| 5 | **HIGH** | Voice | LLM latency tail: 55s outlier + repeated timeouts on free tier; no failover wired | live probe |
| 6 | **HIGH** | Voice | Facility FAQ (hours/address) hallucinated — bot invented a wrong address | live probe |
| 7 | **MEDIUM** | Engine | No past-date/time validation; rolling window keeps stale past slots bookable | failing test x2 |
| 8 | **MEDIUM** | Voice/Engine | Voice path skips input validation: empty phone & 500-char name accepted | failing test x2 |
| 9 | **MEDIUM** | Voice | Hindi (Devanagari) STT garbles the time token ("saat baje" → "seven:zero") | round-trip probe |
| 10 | **MEDIUM** | Voice | No cancellation/lookup tool; bot tells caller "I can't, go to front desk" | live probe |
| 11 | **MEDIUM** | Engine | `get_next_available_slot` ignores time-of-day → offers 6 AM when 7 PM was wanted | code + behavior |
| 12 | **LOW** | Voice | Greeting hardcoded English + duplicated between bot.py and prompt | code review |
| 13 | **LOW** | Frontend | Reschedule time dropdown (06–22h) can't represent off-hour/out-of-range slots | code review |
| 14 | **LOW** | Config | `language_preference` stored & passed but never used | code review |

Existing guarantees that **held up** under testing: the partial-unique-index double-booking
protection (concurrency test + adversarial double-book all pass), multi-section atomic full-court
booking, membership auto-expiry by date, tenant data isolation at the query layer, privacy of
names in availability, and the reschedule rollback (a failed reschedule does **not** lose the
original — verified; session close discards the uncommitted cancel).

---

## CRITICAL

### 1. Phone numbers aren't normalized at write time — group rules & weekly cap silently fail in production
`create_booking` stores the caller's phone **raw** (`customer_phone=phone`). But the group
one-per-timeslot rule and the weekly cap match stored bookings against member records with a raw
SQL `IN`:

```python
# service.py — check_group_restriction / _check_group_weekly_cap
Booking.customer_phone.in_(other_phones)   # other_phones come from Member.phone (raw)
```

Exotel delivers caller IDs as `+919876500002`; facilities store members as `9876500002`. The
booking row is saved as `+919876...`, so the `IN` comparison never matches the member's stored
number — **the group restriction and the shared weekly cap never fire for any real phone call.**
These are headline features in the project summary.

Why the existing suite missed it: `test_group_restriction_blocks_same_timeslot` uses identical
10-digit strings for both the member and the booking, so formats coincidentally match.

**Confirmed by:** `test_group_timeslot_rule_catches_plus91_formatted_booking`,
`test_group_weekly_cap_counts_plus91_formatted_bookings` (both fail).

**Fix:** normalize at the boundary. Store `normalize_phone(phone)` in `_insert_rows`, and
normalize the comparison set. One-line-ish:

```python
# _insert_rows
customer_phone=normalize_phone(phone),
# check_group_restriction / _check_group_weekly_cap: compare normalized to normalized.
# Since customer_phone is now stored normalized, build the IN list from normalized member phones:
other_phones = [normalize_phone(p) for p in other_phones]
```
Add a data migration to normalize existing `bookings.customer_phone`. (Also dedups the
"same person, two formats" loophole in `test_same_caller_can_hold_two_courts_same_time`.)

### 2. The REST API has no authentication — customer PII is world-readable
Every endpoint is open and `client_id` is just a path parameter. `GET /clients/1/bookings`
returns every customer's **name + phone**; changing the number to `/clients/2/...` reads another
tenant. Confirmed live: anonymous requests to both tenants succeeded.

The Postgres RLS policies don't help here: the app connects as the table owner and never sets a
per-request tenant GUC, so RLS is bypassed for every query. RLS only protects against a
direct-to-DB attacker, not against the unauthenticated API.

**Fix (MVP-appropriate):** put the API behind an auth layer before any real deployment — at
minimum a per-client API key/JWT in an `Authorization` header, resolved to `client_id`
server-side (stop trusting the path param). Medium-term: set `SET LOCAL app.client_id = :id` per
request and make RLS `USING (client_id = current_setting('app.client_id')::int)` actually load-bearing.

---

## HIGH

### 3. CORS is hardcoded to localhost — the production dashboard can't reach the API
`main.py` allows only `http://localhost:3000` / `127.0.0.1:3000`. A preflight from a Vercel origin
returns **400 with no `Access-Control-Allow-Origin`**, so the deployed dashboard's `fetch` calls
are blocked by the browser. The dashboard only works when run on the operator's own machine
pointing at `localhost`. This contradicts "deployed to Vercel (Hobby)".

**Fix:** drive allowed origins from env (`ALLOWED_ORIGINS=https://yourapp.vercel.app,...`) and read
it in `add_middleware`. Keep localhost for dev.

### 4. `check_availability` without a time floods the LLM context
Measured live: one no-time availability call for a single sport on the full seed facility returns
**51 options ≈ 3,344 tokens** of JSON. With the system prompt (~1,449 tokens) and the tool schema
(~749 tokens), the free Cerebras tier's **8K-token context** is largely consumed before the
conversation even progresses; a second availability call or a few turns of history overflows it
mid-call. The prompt *tells* the model never to call availability without a time, but nothing
enforces it and the model can still do so (and a full-facility "what's free tomorrow?" legitimately
triggers it).

**Fix:** (a) cap and summarize — return at most ~6 options and a count ("plus 12 more later
slots"); (b) when no time is given, return a compact list of available *start-times* per option,
not every slot; (c) consider raising the context tier or trimming the system prompt (it's verbose).

### 5. LLM latency tail and reliability on the free tier
Warm turns are good (~700 ms TTFT, ~1 s total). But the probe also recorded a single
**55,878 ms** turn and repeated `APITimeoutError`/`APIConnectionError` when turns came
back-to-back. On a phone call a 55-second stall is dead air → the caller hangs up. The config
mentions Claude Haiku as a paid fallback, but the pipeline (`providers.make_llm`) wires exactly one
provider with no timeout or failover.

**Fix:** set a hard per-turn timeout (~4–6 s) and fail over to the secondary LLM (Haiku) on
timeout/error; emit a brief filler ("ek second…") if a turn exceeds ~1.2 s so the line is never
silent. Track p95/p99 latency in `enable_metrics` output.

### 6. Facility FAQ answers are hallucinated
Probe L asked "What are your opening hours and where are you located?" The bot confidently replied
with **"HSR Layout, Sector 2, near the BDA Complex"** — entirely invented; the seeded facility is
in **Vashi, Navi Mumbai**. Hours came out right only by luck (they're in no prompt). The system
prompt gives the model no facility address/hours and doesn't forbid answering, so it confabulates.
Telling a caller the wrong address is a real-world failure.

**Fix:** inject real facility data (address, hours, amenities, directions) into the system prompt,
and add a rule: "If you don't have a fact about the facility, say you'll have someone confirm —
never guess an address, price, or time."

---

## MEDIUM

### 7. No past-date / past-time validation
The engine books any date, including the past. Availability and `create_booking` only "fail" on
past dates today because the seed has no past slots — but the rolling `ensure_window` job **adds**
future days and never removes past ones, so yesterday's slots persist in the DB and become
bookable-in-the-past. An LLM mis-resolving "Monday" to a past Monday would succeed silently.
**Confirmed:** `test_booking_a_past_date_is_rejected`, `test_availability_excludes_past_dates` fail.
**Fix:** reject `date < today` (and `< now` for today's times) in `check_availability` and
`create_booking`; filter past slots in `_free_section_slots`.

### 8. The voice path skips the input validation the REST path has
`CreateBookingRequest` enforces `phone: min_length=4` and `name: max_length=200` — but only on the
REST route. The **voice** tool (`dispatch` → `svc.create_booking`) calls the service with raw args
and bypasses that model entirely. Result: an empty phone books successfully; a 500-char name is
accepted (silently on SQLite; a mid-call `DataError` on Postgres `String(200)` → bot says
"something went wrong"). **Confirmed:** `test_voice_tool_rejects_empty_phone`,
`test_voice_tool_rejects_absurd_name` fail.
**Fix:** validate in the service (the single choke point) — require ≥10 digits after
normalization, truncate/limit name length — so both paths are protected.

### 9. Hindi (Devanagari) STT garbles the booking time
Round-trip probe: ElevenLabs spoke "कल शाम सात बजे" (tomorrow evening 7 o'clock); Deepgram nova-3
`multi` heard **"कल शाम seven:zero बजे"** — the single most important token (the time) corrupted.
English and Hinglish transcribed times correctly. The prompt's read-back rule mitigates this, but
pure-Hindi number recognition is the weakest link in the booking flow.
**Fix:** keep (and strengthen) explicit numeric read-back/confirmation for date & time; consider a
post-STT normalizer for Hindi number words; test with real caller audio, not just TTS.

### 10. No cancellation or booking-lookup tool on voice
Probe K: caller asks to cancel a booking; the bot replies it **can't** and tells them to visit the
front desk — and reveals the system's limits ("through this system"). The dashboard can cancel, but
the receptionist can't. For an "AI receptionist" this is a visible capability gap.
**Fix:** add `find_my_bookings(phone)` and `cancel_booking(booking_id, phone)` voice tools (scoped
to the caller's own phone for privacy), reusing the existing service methods.

### 11. `get_next_available_slot` ignores the time of day
It returns the earliest option from `date` 00:00 onward, so when "7 PM is taken" it offers the
6 AM slot, not the nearest evening one. The prompt promises "the nearest option."
**Fix:** accept the requested time and prefer the nearest slot at/after it on the same day before
rolling to the next day.

---

## LOW

- **12. Greeting** is hardcoded English in `bot.py` *and* re-instructed in the prompt (the prompt's
  greeting instruction is dead since audio is already sent). Make the opener honor the client's
  `language_preference`; drop the duplicate instruction.
- **13. Reschedule modal** offers a fixed 06:00–22:00 hourly `<select>`; a booking at any other
  time renders with no matching option. Derive options from the facility hours/duration.
- **14. `language_preference`** (Client column + `build_system_prompt` param) is never used to
  change behavior — wire it or remove it to avoid false confidence.
- **Deprecation noise:** test suite prints a Starlette/httpx deprecation warning; `next.config.ts`
  is clean. Non-blocking.

---

## Suggested fix order (fastest path to "smooth, seamless, bilingual")

1. **#1 phone normalization** — small change, restores two advertised features. (engine)
2. **#7 past-date guard + #8 service-level validation** — same file, closes booking-integrity holes.
3. **#4 availability payload cap + #6 facility facts in prompt + #5 timeout/failover** — the three
   that most affect live call quality and latency.
4. **#3 CORS env + #2 API auth** — required before any non-local deployment.
5. **#10 cancel/lookup voice tools, #11 next-slot time, #9 Hindi number confirmation** — receptionist completeness.
6. Low-severity polish.

Each engine fix has a corresponding failing test in `test_adversarial_audit.py` that should flip to
green once addressed.
