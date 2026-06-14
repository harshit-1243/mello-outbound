"""Per-call transcript recorder.

Drives two outputs as a call unfolds:
1. A human-readable ``backend/call_logs/<timestamp>.txt`` and a machine-readable ``.jsonl`` —
   flushed on every turn, so even a crashed call leaves a complete-up-to-now transcript the
   operator can read without pasting anything into a chat.
2. On close, best-effort ``Call`` + ``CallTurn`` rows so the dashboard's Live Calls page shows
   the conversation. File writes never fail the call; the DB write is wrapped so a DB outage
   still leaves the on-disk log.

Outcome is derived simply (no NLP): ``missed`` if the caller never spoke, ``booked`` if a
``create_booking`` tool call succeeded during the call, else ``handled``.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from app.db.base import SessionLocal
from app.db.models import (
    CALL_BOOKED,
    CALL_HANDLED,
    CALL_MISSED,
    Call,
    CallTurn,
)
from app.voice import usage

LOG_DIR = Path(__file__).resolve().parents[2] / "call_logs"


@dataclass
class CallRecord:
    call_id: int | None
    txt_path: str
    jsonl_path: str
    outcome: str


class CallLogger:
    def __init__(self, client_id: int, caller_phone: str | None, log_dir: Path | None = None):
        self.client_id = client_id
        self.caller_phone = (caller_phone or "unknown").strip() or "unknown"
        self.started_at = dt.datetime.now()
        self.turns: list[tuple[dt.datetime, str, str]] = []  # (ts, role, text)
        self.language: str | None = None
        self.booked = False
        self._closed = False

        self.dir = log_dir or LOG_DIR
        stem = f"{self.started_at.strftime('%Y%m%dT%H%M%S')}_{client_id}"
        self.txt_path = self.dir / f"{stem}.txt"
        self.jsonl_path = self.dir / f"{stem}.jsonl"
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self.txt_path.write_text(
                f"Mello call log — client {client_id} — caller {self.caller_phone}\n"
                f"started {self.started_at.isoformat(timespec='seconds')}\n"
                + "-" * 60 + "\n",
                encoding="utf-8",
            )
            self.jsonl_path.write_text("", encoding="utf-8")
        except OSError:
            pass  # never let logging break a call

    def log_turn(self, role: str, text: str, language: str | None = None) -> None:
        text = (text or "").strip()
        if not text:
            return
        ts = dt.datetime.now()
        self.turns.append((ts, role, text))
        if language:
            self.language = language
        # Assistant text is what gets synthesized — count it toward Sarvam TTS usage.
        if role == "assistant":
            usage.record_tts_chars(len(text))
        try:
            with self.txt_path.open("a", encoding="utf-8") as f:
                f.write(f"[{ts.strftime('%H:%M:%S')}] {role.upper()}: {text}\n")
            with self.jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": ts.isoformat(timespec="seconds"), "role": role, "text": text, "language": language}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def mark_booking(self) -> None:
        """Called when a create_booking tool call returns booked=True."""
        self.booked = True

    def _derive_outcome(self) -> str:
        if not any(role == "user" for _, role, _ in self.turns):
            return CALL_MISSED
        return CALL_BOOKED if self.booked else CALL_HANDLED

    def _derive_summary(self, outcome: str) -> str:
        first_user = next((t for _, role, t in self.turns if role == "user"), "")
        base = f"Caller: {first_user[:140]}" if first_user else "No caller speech."
        return base + (" — booked." if outcome == CALL_BOOKED else "")

    def close(self, persist: bool = True) -> CallRecord:
        if self._closed:
            return CallRecord(None, str(self.txt_path), str(self.jsonl_path), self._derive_outcome())
        self._closed = True
        ended_at = dt.datetime.now()
        duration = int((ended_at - self.started_at).total_seconds())
        outcome = self._derive_outcome()
        summary = self._derive_summary(outcome)

        try:
            with self.txt_path.open("a", encoding="utf-8") as f:
                f.write("-" * 60 + "\n")
                f.write(f"ended {ended_at.isoformat(timespec='seconds')} · {duration}s · outcome={outcome}\n")
        except OSError:
            pass

        call_id: int | None = None
        if persist:
            call_id = self._persist(ended_at, duration, outcome, summary)
        return CallRecord(call_id, str(self.txt_path), str(self.jsonl_path), outcome)

    def _persist(self, ended_at: dt.datetime, duration: int, outcome: str, summary: str) -> int | None:
        try:
            with SessionLocal() as db:
                call = Call(
                    client_id=self.client_id,
                    caller_phone=self.caller_phone,
                    caller_name=None,
                    started_at=self.started_at,
                    ended_at=ended_at,
                    duration_seconds=duration,
                    outcome=outcome,
                    language=self.language,
                    summary=summary,
                )
                db.add(call)
                db.flush()
                for ts, role, text in self.turns:
                    db.add(CallTurn(call_id=call.id, client_id=self.client_id, role=role, text=text, ts=ts))
                db.commit()
                return call.id
        except Exception as exc:  # noqa: BLE001 — files are already on disk; DB is best-effort
            print(f"[call_logger] DB persist failed ({type(exc).__name__}): {exc}. Transcript saved to {self.txt_path}", flush=True)
            return None
