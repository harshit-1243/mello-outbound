"""FastAPI app exposing the booking engine over REST.

This is the engine's test/admin surface (and what the voice tool handlers call in-process). The
voice WebSocket route (/ws/exotel) is added in M3.
"""
from __future__ import annotations

import datetime as dt

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.booking import errors
from app.booking.schemas import (
    BookingConfirmation,
    BookingSummary,
    CallDetail,
    CallSummary,
    ClientInfo,
    CreateBookingRequest,
    DashboardStats,
    GroupCheckResult,
    MemberInfo,
    MemberSummary,
    OccupancyGrid,
    OptionInfo,
)
from app.booking.service import BookingService
from app.config import settings
from app.db.base import get_session
from app.db.models import Campaign
from app.voice import metrics as outbound_metrics
from app.voice.schemas import CampaignMetrics, CampaignSummary, OutboundContactRow

app = FastAPI(title="mello.ai booking engine", version="0.1.0")

# Browser origins allowed to call the API (local dev + deployed dashboard, via CORS_ORIGINS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    # Skip auth for health check and when no key is configured (local dev).
    if request.url.path == "/health" or not settings.api_key:
        return await call_next(request)
    key = (
        request.headers.get("X-API-Key")
        or request.headers.get("x-api-key")
        or (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    )
    if key != settings.api_key:
        return JSONResponse(
            status_code=401,
            content={"code": "unauthorized", "detail": "Invalid or missing API key."},
        )
    return await call_next(request)

_STATUS = {
    errors.SlotNotFound: 404,
    errors.SlotUnavailable: 409,
    errors.MembershipRequired: 403,
    errors.GroupRestrictionViolation: 409,
    errors.InvalidInput: 422,
}


@app.exception_handler(errors.BookingError)
async def booking_error_handler(_: Request, exc: errors.BookingError):
    status = next((code for typ, code in _STATUS.items() if isinstance(exc, typ)), 400)
    return JSONResponse(status_code=status, content={"code": exc.code, "detail": exc.message})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/usage")
def usage() -> dict:
    """Free-credit / usage monitor: per-provider usage vs configured limits + any quota alerts.
    Account-wide (not per-tenant) since the AI provider credits are shared across the deployment."""
    from app.voice.usage import snapshot

    return snapshot()


@app.get("/clients/{client_id}/availability", response_model=list[OptionInfo])
def availability(
    client_id: int,
    sport: str,
    date: dt.date,
    time: dt.time | None = None,
    db: Session = Depends(get_session),
):
    return BookingService(db, client_id).check_availability(sport, date, time)


@app.get("/clients/{client_id}/members/{phone}", response_model=MemberInfo)
def member(client_id: int, phone: str, db: Session = Depends(get_session)):
    return BookingService(db, client_id).verify_member(phone)


class GroupCheckRequest(BaseModel):
    phone: str
    date: dt.date
    time: dt.time


@app.post("/clients/{client_id}/group-check", response_model=GroupCheckResult)
def group_check(client_id: int, body: GroupCheckRequest, db: Session = Depends(get_session)):
    return BookingService(db, client_id).check_group_restriction(body.phone, body.date, body.time)


@app.post("/clients/{client_id}/bookings", response_model=BookingConfirmation)
def create_booking(client_id: int, body: CreateBookingRequest, db: Session = Depends(get_session)):
    svc = BookingService(db, client_id)
    return svc.create_booking(
        name=body.name,
        phone=body.phone,
        offering_id=body.offering_id,
        date=body.date,
        time=body.time,
        source="manual",
    )


@app.get("/clients/{client_id}/next-slot", response_model=OptionInfo | None)
def next_slot(client_id: int, sport: str, date: dt.date, db: Session = Depends(get_session)):
    return BookingService(db, client_id).get_next_available_slot(sport, date)


# ---- dashboard read endpoints (operator console) ----

@app.get("/clients/{client_id}", response_model=ClientInfo)
def client_info(client_id: int, db: Session = Depends(get_session)):
    return BookingService(db, client_id).get_client_info()


@app.get("/clients/{client_id}/members", response_model=list[MemberSummary])
def list_members(client_id: int, db: Session = Depends(get_session)):
    return BookingService(db, client_id).list_members()


@app.get("/clients/{client_id}/occupancy", response_model=OccupancyGrid)
def occupancy(client_id: int, date: dt.date, db: Session = Depends(get_session)):
    return BookingService(db, client_id).get_occupancy(date)


@app.get("/clients/{client_id}/stats", response_model=DashboardStats)
def dashboard_stats(client_id: int, db: Session = Depends(get_session)):
    return BookingService(db, client_id).get_dashboard_stats()


@app.get("/clients/{client_id}/calls", response_model=list[CallSummary])
def list_calls(client_id: int, db: Session = Depends(get_session)):
    return BookingService(db, client_id).list_calls()


@app.get("/clients/{client_id}/calls/{call_id}", response_model=CallDetail)
def get_call(client_id: int, call_id: int, db: Session = Depends(get_session)):
    return BookingService(db, client_id).get_call(call_id)


# ---- dashboard write endpoints ----

@app.get("/clients/{client_id}/bookings", response_model=list[BookingSummary])
def list_bookings(client_id: int, include_cancelled: bool = False, db: Session = Depends(get_session)):
    return BookingService(db, client_id).list_bookings(include_cancelled=include_cancelled)


@app.post("/clients/{client_id}/bookings/{booking_id}/cancel")
def cancel_booking(client_id: int, booking_id: int, db: Session = Depends(get_session)):
    BookingService(db, client_id).cancel_booking(booking_id)
    return {"cancelled": True}


class RescheduleRequest(BaseModel):
    date: dt.date
    time: dt.time


@app.post("/clients/{client_id}/bookings/{booking_id}/reschedule", response_model=BookingConfirmation)
def reschedule_booking(
    client_id: int, booking_id: int, body: RescheduleRequest, db: Session = Depends(get_session)
):
    return BookingService(db, client_id).reschedule_booking(booking_id, body.date, body.time)


# ---- outbound (Mello Outbound) read endpoints — same dashboard, new section ----

@app.get("/objectives")
def list_objectives() -> list[dict]:
    """The menu of outbound objectives (label + suited client sectors) for the campaign builder."""
    from app.voice.objective import OBJECTIVES

    return [{"key": k, **v} for k, v in OBJECTIVES.items()]


@app.get("/clients/{client_id}/campaigns", response_model=list[CampaignSummary])
def list_campaigns(client_id: int, db: Session = Depends(get_session)):
    return outbound_metrics.list_campaigns(db, client_id)


def _owned_campaign(db: Session, client_id: int, campaign_id: int) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.client_id != client_id:
        raise HTTPException(status_code=404, detail="campaign not found")
    return campaign


@app.get("/clients/{client_id}/campaigns/{campaign_id}/metrics", response_model=CampaignMetrics)
def campaign_metrics(client_id: int, campaign_id: int, db: Session = Depends(get_session)):
    return outbound_metrics.campaign_metrics(db, _owned_campaign(db, client_id, campaign_id))


@app.get("/clients/{client_id}/campaigns/{campaign_id}/contacts", response_model=list[OutboundContactRow])
def campaign_contacts(client_id: int, campaign_id: int, db: Session = Depends(get_session)):
    _owned_campaign(db, client_id, campaign_id)  # tenant check
    return outbound_metrics.campaign_contacts(db, campaign_id)
