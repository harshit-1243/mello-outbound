# Mello — live voice demo (talk with your mic, book by voice, watch the dashboard)

Talk to Mello in your **browser with your microphone**, book an appointment by voice, and see it
appear on the **dashboard** a couple of seconds later. No phone number needed.

Brain = **Cerebras**, voice (speech-to-text + text-to-speech) = **Sarvam**, all sharing one
database so the booking shows up on the dashboard.

---

## 1. One-time setup

**Paste your two keys** into `backend/.env` (already created for you):

```
CEREBRAS_API_KEY=your_cerebras_key
SARVAM_API_KEY=your_sarvam_key
```

Install (already done if you ran the build steps):

```bash
cd backend
py -3.12 -m venv .venv                       # if not created yet
.venv/Scripts/python -m pip install -r requirements.txt    # voice stack (one-time, ~a few min)
.venv/Scripts/python -m app.seed             # demo facility "Smash Arena"
.venv/Scripts/python -m app.seed_outbound    # demo outbound campaign (optional, for the Outbound tab)

cd ../frontend
npm install                                  # one-time
```

---

## 2. Run it — three terminals

All three share `backend/.env` (so they all use the same `demo.db`).

**Terminal 1 — REST API (feeds the dashboard):**
```bash
cd backend
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

**Terminal 2 — the voice bot (your mic).** Pick ONE mode (same URL, default **http://localhost:7860**):

```bash
cd backend
# INBOUND — you call Mello (it greets, you ask to book):
.venv/Scripts/python -m app.voice.bot

# …or OUTBOUND — Mello calls YOU (it speaks first and drives the call):
.venv/Scripts/python -m app.voice.outbound_bot
```
Open the URL, click **Connect**, allow the mic. (Run only one of the two at a time — same port.)

**Terminal 3 — the dashboard:**
```bash
cd frontend
npm run dev
```
Open **http://localhost:3000**.

---

## 3. The demo flow

1. On **http://localhost:7860**, click **Connect** and say hello — Mello greets you and asks how it
   can help.
2. Book by voice, e.g. *"Book badminton tomorrow at 7 PM"* → it checks availability, asks your name
   + number, reads back the details, and confirms.
3. Switch to the **dashboard (http://localhost:3000)** — within ~3 seconds the new **booking** shows
   on Overview / Bookings, and the **call + transcript** shows under Calls.

That's the full loop: **your voice → Mello → a real booking → live on the dashboard.**

### Outbound mode (Mello calls you first)

1. Run `python -m app.voice.outbound_bot` (Terminal 2), open the URL, click **Connect**.
2. The moment you connect, **Mello speaks first** — e.g. *"Hi! This is Mello from Smash Arena. I
   just wanted to confirm your tomorrow 4 PM booking — is that still good for you?"*
3. Answer by voice: *"yes"* (confirm), *"can we move it to…"* (reschedule), or *"please stop
   calling"* (opt-out). Mello drives to the goal and wraps up.
4. On the **dashboard → Outbound tab**, that contact's pill flips (e.g. → **CONFIRMED**) and the
   campaign metrics move within ~3 seconds.

---

## Real call to YOUR phone (Twilio trial — calls only your verified number)

No purchased number needed. A Twilio **trial** gives a free number and can call **verified** numbers.
Mello is hard-locked to an **allowlist**, so it can *only* ever dial the number you list.

**One-time (Twilio console):**
1. Create a free trial account → note the **trial phone number**.
2. **Verify your mobile**: Console → Phone Numbers → *Verified Caller IDs* → add your number (enter the OTP).
3. Enable India: Console → Voice → *Geographic Permissions* → tick **India** (needed to call +91).

**Fill `backend/.env`:**
```
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+1...        # your trial number
OUTBOUND_TEST_NUMBERS=+9198...  # YOUR verified mobile (the only number Mello may call)
PUBLIC_BASE_URL=                # filled in the next step
```

**Expose the server so Twilio can reach it** (Twilio can't see localhost):
```bash
ngrok http 8000        # copy the https URL it shows
```
Put that URL in `PUBLIC_BASE_URL` in `.env`, then (re)start the API:
```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000
```
(You also need `python -m app.seed` + `python -m app.seed_outbound` once, and your Cerebras/Sarvam keys in `.env`.)

**Make Mello call you:**
```bash
curl -X POST http://localhost:8000/clients/1/test-call \
  -H "Content-Type: application/json" -d "{\"to\":\"+9198XXXXXXXX\"}"
```
Your phone rings → after Twilio's short "trial" message, **Mello speaks first** and you have the
conversation. Confirm/reschedule/opt-out by voice, then watch the **dashboard → Outbound tab**
update within a few seconds. (Any number not in `OUTBOUND_TEST_NUMBERS` is refused with 403.)

> The phone call runs inside the API server (`/ws/twilio`) — you do **not** run `app.voice.outbound_bot`
> for this; that one is the browser-mic version.

## Notes
- Mic + audio work over **localhost** (a secure context); browsers need that for mic access.
- Mello opens in **English** and switches to Hindi if you do.
- Speak naturally and pause — it waits ~1s of silence before replying.
- The **Outbound** tab shows campaigns (Mello calling out); this mic demo is the inbound
  receptionist (you calling Mello). Both write to the same dashboard.
