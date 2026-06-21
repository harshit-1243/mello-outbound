"""Outbound campaign metrics — the numbers the dashboard's Outbound section shows.

Per campaign: calls made, answer/connect rate, AMD breakdown, qualified/booked, goal-completion
rate, average handle time, total cost + cost per successful outcome, and opt-out rate. Computed in
Python from the campaign's attempts + contacts (clear and portable; fine at per-campaign volumes).
"""
from __future__ import annotations

from collections import Counter

from sqlalchemy import select

from app.db.models import (
    AMD_HUMAN,
    AMD_IVR,
    AMD_UNKNOWN,
    AMD_VOICEMAIL,
    CONTACT_DONE,
    CONTACT_EXHAUSTED,
    CONTACT_IN_FLIGHT,
    CONTACT_PENDING,
    DISPOSITION_CONFIRMED,
    DISPOSITION_OPT_OUT,
    DISPOSITION_RESCHEDULED,
    CallAttempt,
    Campaign,
    OutboundContact,
)

_SUCCESS = {DISPOSITION_CONFIRMED, DISPOSITION_RESCHEDULED}


def _pct(n: int, d: int) -> int:
    return round(100 * n / d) if d else 0


def campaign_metrics(session, campaign: Campaign) -> dict:
    attempts = list(session.scalars(select(CallAttempt).where(CallAttempt.campaign_id == campaign.id)))
    contacts = list(session.scalars(select(OutboundContact).where(OutboundContact.campaign_id == campaign.id)))

    calls_made = len(attempts)
    answered_attempts = [a for a in attempts if a.answered]
    answered = len(answered_attempts)
    amd = Counter(a.amd_result for a in answered_attempts)  # AMD only meaningful once answered
    human_contacts = {a.contact_id for a in attempts if a.amd_result == AMD_HUMAN}
    handle = [a.duration_s for a in answered_attempts if a.duration_s]
    total_cost = round(sum(float(a.cost_inr or 0) for a in attempts), 2)

    by_state = Counter(c.state for c in contacts)
    booked = sum(1 for c in contacts if c.last_disposition == DISPOSITION_CONFIRMED)
    goal_completed = sum(1 for c in contacts if c.last_disposition in _SUCCESS)
    opt_outs = sum(1 for c in contacts if c.last_disposition == DISPOSITION_OPT_OUT)
    contacts_total = len(contacts)

    return {
        "campaign_id": campaign.id,
        "name": campaign.name,
        "objective_type": campaign.objective_type,
        "status": campaign.status,
        "contacts_total": contacts_total,
        "contacts_pending": by_state.get(CONTACT_PENDING, 0) + by_state.get(CONTACT_IN_FLIGHT, 0),
        "contacts_done": by_state.get(CONTACT_DONE, 0),
        "contacts_exhausted": by_state.get(CONTACT_EXHAUSTED, 0),
        "calls_made": calls_made,
        "answered": answered,
        "answer_rate_pct": _pct(answered, calls_made),
        "amd_human": amd.get(AMD_HUMAN, 0),
        "amd_voicemail": amd.get(AMD_VOICEMAIL, 0),
        "amd_ivr": amd.get(AMD_IVR, 0),
        "amd_unknown": amd.get(AMD_UNKNOWN, 0),
        "qualified": len(human_contacts),
        "booked": booked,
        "goal_completed": goal_completed,
        "goal_completion_rate_pct": _pct(goal_completed, contacts_total),
        "avg_handle_seconds": round(sum(handle) / len(handle)) if handle else 0,
        "total_cost_inr": total_cost,
        "cost_per_success_inr": round(total_cost / goal_completed, 2) if goal_completed else None,
        "opt_outs": opt_outs,
        "opt_out_rate_pct": _pct(opt_outs, contacts_total),
        "spent_inr": float(campaign.spent_inr or 0),
        "budget_cap_inr": float(campaign.budget_cap_inr or 0),
    }


def list_campaigns(session, client_id: int) -> list[dict]:
    camps = list(session.scalars(select(Campaign).where(Campaign.client_id == client_id).order_by(Campaign.id.desc())))
    rows = []
    for c in camps:
        m = campaign_metrics(session, c)
        rows.append({
            "id": c.id, "name": c.name, "objective_type": c.objective_type, "status": c.status,
            "contacts_total": m["contacts_total"], "calls_made": m["calls_made"],
            "answer_rate_pct": m["answer_rate_pct"], "booked": m["booked"],
            "spent_inr": m["spent_inr"], "budget_cap_inr": m["budget_cap_inr"],
        })
    return rows


def campaign_contacts(session, campaign_id: int, limit: int = 200) -> list[dict]:
    rows = list(
        session.scalars(
            select(OutboundContact).where(OutboundContact.campaign_id == campaign_id).order_by(OutboundContact.id).limit(limit)
        )
    )
    return [
        {"id": r.id, "name": r.name, "phone": r.phone, "state": r.state,
         "last_disposition": r.last_disposition, "attempt_count": r.attempt_count}
        for r in rows
    ]
