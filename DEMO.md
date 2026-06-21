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

**Terminal 2 — the voice bot (your mic):**
```bash
cd backend
.venv/Scripts/python -m app.voice.bot
```
It prints a URL (default **http://localhost:7860**). Open it, click **Connect**, allow the mic.

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

---

## Notes
- Mic + audio work over **localhost** (a secure context); browsers need that for mic access.
- Mello opens in **English** and switches to Hindi if you do.
- Speak naturally and pause — it waits ~1s of silence before replying.
- The **Outbound** tab shows campaigns (Mello calling out); this mic demo is the inbound
  receptionist (you calling Mello). Both write to the same dashboard.
