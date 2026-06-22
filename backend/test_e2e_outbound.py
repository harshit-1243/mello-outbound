"""E2E outbound check: drive the LIVE call tool path (_run) and confirm it lands in Supabase +
the dashboard, without placing a real call. Proves: agent tool fires → SQLite + Supabase → dashboard.
"""
from __future__ import annotations

import httpx
from sqlalchemy import select

from app.config import settings

settings.outbound_dlt_registered = True

from app.db.base import SessionLocal  # noqa: E402
from app.db.models import CONTACT_PENDING, Campaign, OutboundContact  # noqa: E402
from app.voice.outbound_pipeline_tools import _run  # noqa: E402

REST = settings.supabase_url.rstrip("/") + "/rest/v1"
H = {"apikey": settings.supabase_service_key, "Authorization": f"Bearer {settings.supabase_service_key}"}
PHONE = "+910000000077"
CAMP_NAME = "Membership renewals — June"


def supa_get(table: str, params: dict):
    return httpx.get(f"{REST}/{table}", headers=H, params=params, timeout=10).json()


def main() -> None:
    # clean any prior test row
    httpx.request("DELETE", f"{REST}/outbound_contacts", headers=H, params={"phone": f"eq.{PHONE}"}, timeout=10)

    db = SessionLocal()
    try:
        camp = db.scalar(select(Campaign).where(Campaign.name == CAMP_NAME))
        if not camp:
            print("FAIL: SQLite campaign missing — run seed_outbound_all"); return
        contact = OutboundContact(
            client_id=camp.client_id, campaign_id=camp.id, phone=PHONE, name="E2E Outbound Test",
            consent_basis="existing_customer", state=CONTACT_PENDING, context_json={"service": "gym membership"},
        )
        db.add(contact); db.commit()
        cid = contact.id
    finally:
        db.close()

    before = supa_get("outbound_contacts", {"select": "id", "phone": f"eq.{PHONE}"})
    print(f"BEFORE: Supabase has {len(before)} row(s) for {PHONE}")

    # THE LIVE CALL PATH: the LLM calling mark_renewal runs exactly this.
    out = _run(cid, camp.id, "mark_renewal", {})
    print(f"_run(mark_renewal): ok={out['ok']} done={out['done']}")

    rows = supa_get("outbound_contacts", {"select": "id,name,phone,campaign_id,last_disposition,state", "phone": f"eq.{PHONE}"})
    print(f"AFTER : Supabase has {len(rows)} row(s): {rows}")
    if rows:
        att = supa_get("outbound_call_attempts", {"select": "disposition,answered,amd_result", "contact_id": f"eq.{rows[0]['id']}"})
        print(f"        attempts: {att}")

    ok = bool(rows) and rows[0]["last_disposition"] == "confirmed"
    print("RESULT:", "PASS - outbound live path -> Supabase" if ok else "FAIL")


if __name__ == "__main__":
    main()
