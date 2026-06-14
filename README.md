# mello.ai

A 24/7 **AI phone receptionist for Indian sports & recreation facilities** (turfs, courts, arenas).
Mello answers inbound calls, books slots in real time in **Hindi + English (Hinglish)**, enforces
membership / group / privacy rules, logs every call transcript, and surfaces it all on an operator
dashboard.

Built to be **clone-and-run**: bring your own API keys, point it at your own database, and go. The
booking engine runs and passes its full test suite on **SQLite with zero accounts** — you only need
keys for the live voice agent.

```
Caller ─▶ Exotel (phone) ─▶ Pipecat pipeline:
            Silero VAD ─▶ Sarvam STT (saarika) ─▶ Cerebras LLM (zai-glm-4.7 + booking tools)
                       ─▶ Sarvam TTS (bulbul) ─▶ Caller
                                  │
                       Booking engine (FastAPI) ──▶ Postgres (Supabase) / SQLite (dev)
                                  │
                       Operator dashboard (Next.js)  ◀── live bookings, calls, members, credits
```

The voice stack is deliberately **Sarvam (STT+TTS) + Cerebras (LLM)** — India-native Hinglish at low
cost. Other providers exist in the code as interim options but are off by default.

---

## Repo layout

| Path | What |
|---|---|
| `backend/` | FastAPI booking engine + REST/dashboard API + the Pipecat voice agent (`app/voice/`) |
| `frontend/` | Next.js operator dashboard (Overview, Live Calls, Bookings, Members, Reports, Settings) |
| `backend/Dockerfile`, `render.yaml` | Deploy configs for the backend web service |

---

## Bring your own keys

| Service | Needed for | Cost | Where |
|---|---|---|---|
| **Cerebras** | LLM (reasoning + booking tools) | Free tier ≈ 1M tokens/day | https://cloud.cerebras.ai |
| **Sarvam** | STT + TTS (Hinglish voice) | Free credits, then pay-as-you-go | https://dashboard.sarvam.ai |
| **Supabase** (or any Postgres) | Production database | Free tier | https://supabase.com |
| Exotel | Real phone calls (telephony) | Paid + Indian-business KYC | https://exotel.com |
| WhatsApp BSP (Interakt/Wati) | Booking confirmations | Paid + template approval | — |

The **booking engine + dashboard need none of these** (SQLite). The **voice agent** needs Cerebras +
Sarvam. Telephony (Exotel) and WhatsApp are optional later stages.

---

## Quick start (local)

### 1. Backend — booking engine + dashboard API

```bash
cd backend
python -m venv .venv
# Windows PowerShell:  .venv\Scripts\Activate.ps1
# macOS/Linux:         source .venv/bin/activate

pip install -r requirements-core.txt      # engine + API only (lightweight)
cp .env.example .env                       # then edit .env (works as-is for SQLite)

python -m app.seed                         # seed a demo facility (Smash Arena)
uvicorn app.main:app --reload              # → http://127.0.0.1:8000/docs
```

Run the test suite (SQLite in-memory, no accounts): `pip install pytest && pytest`

### 2. Frontend — operator dashboard

```bash
cd frontend
npm install
cp .env.example .env.local                 # NEXT_PUBLIC_API_BASE defaults to localhost:8000
npm run dev                                # → http://localhost:3000
```

### 3. Voice agent (needs Cerebras + Sarvam keys)

```bash
cd backend
pip install -r requirements.txt            # full install (adds the voice/ML stack)
# Put CEREBRAS_API_KEY and SARVAM_API_KEY in backend/.env, then:
python -m app.voice.bot
```

Open the printed URL (**http://localhost:7860**), click **Connect**, allow the mic, and talk. The
first connect downloads the Silero VAD model (~10s, one-time). Every call is written to
`backend/call_logs/` **and** to the database, and shows up on the dashboard's **Live Calls** page.

---

## Database

- **Default (local):** SQLite at `backend/mello_dev.db` — automatic, nothing to configure.
- **Production (Postgres/Supabase):** set `DATABASE_URL` in `backend/.env` to your connection URI
  (`postgres://` or `postgresql://` both work). Then create the tables and seed once:

  ```bash
  cd backend
  python -m app.db.init_db        # create all tables on the configured DB
  python -m app.seed              # seed the demo facility
  # Supabase + Row-Level Security: python -m app.db.migrate_supabase
  ```

---

## Deploy

**Backend** → any container/Python host. Two easy paths:

- **Render (one click):** New → Blueprint → point at this repo (`render.yaml`). After it builds, set
  `DATABASE_URL`, `CEREBRAS_API_KEY`, `SARVAM_API_KEY`, and `CORS_ORIGINS` (your dashboard URL) in the
  Render dashboard. Then run the DB setup once (Render Shell): `python -m app.db.init_db && python -m app.seed`.
- **Docker / Railway / Fly:** `backend/Dockerfile` serves the API on `$PORT`. Set the same env vars.

**Frontend** → **Vercel**: import the repo, set **Root Directory = `frontend`**, and add env vars
`NEXT_PUBLIC_API_BASE=https://<your-backend-url>` and (if you set a backend `API_KEY`)
`NEXT_PUBLIC_API_KEY=<same key>`. Set the backend's `CORS_ORIGINS` to your Vercel URL.

**Voice agent** → runs as a long-lived process (WebRTC). Run it on a VM or locally for now; phone
calls go live once Exotel telephony (KYC) is connected.

---

## Configuration reference

Everything is environment-driven (see `backend/.env.example` for the annotated list). Highlights:

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | _(blank → SQLite)_ | Postgres/Supabase connection string |
| `LLM_PROVIDER` / `CEREBRAS_MODEL` | `cerebras` / `zai-glm-4.7` | reasoning model |
| `STT_PROVIDER` / `SARVAM_STT_MODEL` | `sarvam` / `saarika:v2.5` | speech-to-text (preserves Hinglish) |
| `TTS_PROVIDER` / `SARVAM_TTS_MODEL` | `sarvam` / `bulbul:v2` | text-to-speech voice |
| `CORS_ORIGINS` | localhost:3000 | browser origins allowed to call the API |
| `API_KEY` | _(blank → no auth)_ | REST API key (`X-API-Key`) |
| `*_DAILY_*_LIMIT` | — | free-tier ceilings for the credit monitor |

### Free-credit monitor

`GET /usage` reports per-provider usage (Cerebras tokens, Sarvam characters/seconds) against the
configured daily limits, and raises an alert when a provider returns a quota/credit error — surfaced
as a banner on the dashboard so you know before you run out. Set the `*_DAILY_*_LIMIT` vars to your
plan's actual allowances for proactive 80% / 100% warnings.

---

## Status

- ✅ Booking engine — multi-tenant schema, the booking operations, DB-level double-booking guard,
  membership / group / privacy rules. Full test suite green.
- ✅ REST + dashboard API — availability, bookings, members, occupancy, stats, calls, usage.
- ✅ Operator dashboard — 6 pages wired to live data.
- ✅ Voice agent — Sarvam + Cerebras pipeline, call transcript logging, credit monitor.
- ⏳ Exotel telephony (KYC) · WhatsApp confirmations — pending vendor onboarding.
