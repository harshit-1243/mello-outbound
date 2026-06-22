"""Mirror live outbound call outcomes into the shared Supabase project (Phase 2).

The dashboard reads outbound from Supabase's outbound_* tables. The live phone agent persists to its
own SQLite first (source of truth for the engine); this best-effort mirror upserts the same outcome
into Supabase so a real call to your number shows on the one dashboard. Matched to the Supabase
campaign by NAME (the seeded campaigns share names), so a live call lands in the right campaign.

Never raises into the call path — any failure is logged and swallowed (SQLite stays authoritative).
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _headers() -> dict:
    k = settings.supabase_service_key
    return {
        "apikey": k,
        "Authorization": f"Bearer {k}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def configured() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_key)


def sync_outcome(
    *,
    campaign_name: str,
    objective_type: str,
    name: str | None,
    phone: str,
    disposition: str,
    state: str,
    answered: bool = True,
    amd_result: str = "human",
    duration_s: int = 0,
    cost_inr: float = 0.0,
) -> None:
    """Upsert (campaign → contact → attempt) into Supabase for one terminal outcome."""
    if not configured():
        return
    rest = settings.supabase_url.rstrip("/") + "/rest/v1"
    fac = settings.outbound_facility_id
    h = _headers()
    try:
        with httpx.Client(timeout=10) as c:
            # campaign: find by name (seeded names match) or create
            r = c.get(f"{rest}/outbound_campaigns", headers=h, params={
                "select": "id", "facility_id": f"eq.{fac}", "name": f"eq.{campaign_name}", "limit": "1"})
            rows = r.json() if r.is_success else []
            if rows:
                camp_id = rows[0]["id"]
            else:
                r = c.post(f"{rest}/outbound_campaigns", headers=h, json={
                    "facility_id": fac, "name": campaign_name, "objective_type": objective_type,
                    "status": "active", "budget_cap_inr": 500})
                camp_id = r.json()[0]["id"]

            # contact: find by phone within campaign, bump attempt + disposition; else create
            r = c.get(f"{rest}/outbound_contacts", headers=h, params={
                "select": "id,attempt_count", "campaign_id": f"eq.{camp_id}", "phone": f"eq.{phone}", "limit": "1"})
            rows = r.json() if r.is_success else []
            if rows:
                contact_id = rows[0]["id"]
                attempts = int(rows[0].get("attempt_count") or 0) + 1
                c.patch(f"{rest}/outbound_contacts", headers=h, params={"id": f"eq.{contact_id}"}, json={
                    "last_disposition": disposition, "state": state, "attempt_count": attempts})
            else:
                r = c.post(f"{rest}/outbound_contacts", headers=h, json={
                    "facility_id": fac, "campaign_id": camp_id, "name": name, "phone": phone,
                    "state": state, "last_disposition": disposition, "attempt_count": 1})
                contact_id = r.json()[0]["id"]

            # attempt row (powers the metrics)
            c.post(f"{rest}/outbound_call_attempts", headers=h, json={
                "facility_id": fac, "campaign_id": camp_id, "contact_id": contact_id,
                "answered": answered, "amd_result": amd_result, "disposition": disposition,
                "duration_s": duration_s, "cost_inr": cost_inr})
    except Exception:  # noqa: BLE001 — never break the call; SQLite remains the source of truth
        logger.warning("Supabase outbound mirror failed (call unaffected)", exc_info=True)
