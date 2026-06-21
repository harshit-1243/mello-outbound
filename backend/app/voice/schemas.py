"""Pydantic response models for the outbound dashboard endpoints (served by app.main)."""
from __future__ import annotations

from pydantic import BaseModel


class CampaignSummary(BaseModel):
    id: int
    name: str
    objective_type: str
    status: str
    contacts_total: int
    calls_made: int
    answer_rate_pct: int
    booked: int
    spent_inr: float
    budget_cap_inr: float


class CampaignMetrics(BaseModel):
    campaign_id: int
    name: str
    objective_type: str
    status: str
    contacts_total: int
    contacts_pending: int
    contacts_done: int
    contacts_exhausted: int
    calls_made: int
    answered: int
    answer_rate_pct: int
    amd_human: int
    amd_voicemail: int
    amd_ivr: int
    amd_unknown: int
    qualified: int
    booked: int
    goal_completed: int
    goal_completion_rate_pct: int
    avg_handle_seconds: int
    total_cost_inr: float
    cost_per_success_inr: float | None
    opt_outs: int
    opt_out_rate_pct: int
    spent_inr: float
    budget_cap_inr: float


class OutboundContactRow(BaseModel):
    id: int
    name: str | None
    phone: str
    state: str
    last_disposition: str | None
    attempt_count: int
