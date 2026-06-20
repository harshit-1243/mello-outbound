"""Progressive outbound dialer — places ONE call at a time, only after the compliance gate.

Design rules (from the brief):
- PROGRESSIVE only — one live call per worker; never predictive/over-dial (a bot can't handle
  abandoned calls). Concurrency is achieved by running N workers, each doing one call at a time.
- The compliance gate runs before every dial; an ineligible contact is never dialed.
- Per-campaign ₹ budget cap is enforced — the dialer stops when the cap is hit.
- Idempotent: a contact is claimed (state -> in_flight + a short lease) before dialing, so it can't
  be picked twice. On Postgres, prod adds ``SELECT ... FOR UPDATE SKIP LOCKED``; the lease is the
  crash-safe backstop (a dead worker's lease expires and the contact becomes claimable again).

Disposition→retry scheduling is intentionally minimal here (terminal -> done, else pending or
exhausted); Stage 6 adds the backoff/next_attempt_at logic. Real carrier bridging + the goal-driven
bot are later stages — this stage runs end-to-end today via the SimulatedProvider.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import or_, select

from app.db.models import (
    CONTACT_DONE,
    CONTACT_EXHAUSTED,
    CONTACT_IN_FLIGHT,
    CONTACT_PENDING,
    CONTACT_SKIPPED,
    TERMINAL_DISPOSITIONS,
    CallAttempt,
    Campaign,
    OutboundContact,
)
from app.voice.compliance import (
    REASON_MAX_ATTEMPTS,
    REASON_NO_CONSENT,
    REASON_OPTED_OUT,
    is_dial_eligible,
)
from app.voice.telephony import DialResult, SimulatedProvider, TelephonyProvider

LEASE_SECONDS = 120
# Gate reasons that permanently disqualify THIS contact (mark it, move on).
_PERMANENT_SKIP = {REASON_OPTED_OUT, REASON_NO_CONSENT}


@dataclass
class DialerResult:
    status: str  # dialed | skipped | blocked | no_eligible | budget_exhausted
    contact_id: int | None = None
    disposition: str | None = None
    reason: str | None = None


def _utcnow() -> dt.datetime:
    return dt.datetime.utcnow()  # naive UTC, matching CallAttempt.placed_at storage


def _next_candidate(session, campaign: Campaign, now: dt.datetime) -> OutboundContact | None:
    """The next pending contact whose retry time (if any) has arrived. Lowest id first (fair)."""
    return session.scalar(
        select(OutboundContact)
        .where(
            OutboundContact.campaign_id == campaign.id,
            OutboundContact.state == CONTACT_PENDING,
            or_(OutboundContact.next_attempt_at.is_(None), OutboundContact.next_attempt_at <= now),
        )
        .order_by(OutboundContact.id)
        .limit(1)
    )


def run_once(session, campaign: Campaign, provider: TelephonyProvider | None = None, now: dt.datetime | None = None) -> DialerResult:
    """Try to place exactly one call for this campaign. Returns what happened."""
    provider = provider or SimulatedProvider()
    now = now or _utcnow()

    cap = float(campaign.budget_cap_inr or 0)
    if cap and float(campaign.spent_inr or 0) >= cap:
        return DialerResult("budget_exhausted")

    contact = _next_candidate(session, campaign, now)
    if contact is None:
        return DialerResult("no_eligible")

    gate = is_dial_eligible(session, contact, campaign, now=now)  # contact still PENDING here
    if not gate.eligible:
        if gate.reason in _PERMANENT_SKIP:
            contact.state = CONTACT_SKIPPED
            contact.last_disposition = gate.reason
            session.commit()
            return DialerResult("skipped", contact.id, reason=gate.reason)
        if gate.reason == REASON_MAX_ATTEMPTS:
            contact.state = CONTACT_EXHAUSTED
            session.commit()
            return DialerResult("skipped", contact.id, reason=gate.reason)
        # Campaign-level / transient block (outside window, daily cap, DLT off): stop, leave pending.
        return DialerResult("blocked", contact.id, reason=gate.reason)

    # Claim the contact so no other worker can pick it (progressive + idempotent).
    contact.state = CONTACT_IN_FLIGHT
    contact.leased_until = now + dt.timedelta(seconds=LEASE_SECONDS)
    session.flush()

    result = provider.place_call(to=contact.phone, context=contact.context_json or {})
    _record_attempt(session, campaign, contact, result)
    _finalize_contact(contact, campaign, result)
    campaign.spent_inr = float(campaign.spent_inr or 0) + float(result.cost_inr)
    session.commit()
    return DialerResult("dialed", contact.id, disposition=result.disposition)


def run_campaign(session, campaign: Campaign, provider: TelephonyProvider | None = None, max_calls: int = 1000) -> list[DialerResult]:
    """Drive a campaign sequentially (one worker) until nothing's left, budget hit, or blocked."""
    provider = provider or SimulatedProvider()
    out: list[DialerResult] = []
    for _ in range(max_calls):
        r = run_once(session, campaign, provider)
        out.append(r)
        if r.status in ("no_eligible", "budget_exhausted", "blocked"):
            break
    return out


def _record_attempt(session, campaign: Campaign, contact: OutboundContact, res: DialResult) -> None:
    session.add(
        CallAttempt(
            client_id=contact.client_id,
            campaign_id=campaign.id,
            contact_id=contact.id,
            provider_call_sid=res.provider_call_sid,
            answered=res.answered,
            amd_result=res.amd_result,
            disposition=res.disposition,
            duration_s=res.duration_s,
            cost_inr=res.cost_inr,
        )
    )


def _finalize_contact(contact: OutboundContact, campaign: Campaign, res: DialResult) -> None:
    contact.attempt_count += 1
    contact.last_disposition = res.disposition
    contact.leased_until = None
    if res.disposition in TERMINAL_DISPOSITIONS:
        contact.state = CONTACT_DONE
    elif contact.attempt_count >= campaign.max_attempts:
        contact.state = CONTACT_EXHAUSTED
    else:
        contact.state = CONTACT_PENDING  # Stage 6 adds next_attempt_at backoff
