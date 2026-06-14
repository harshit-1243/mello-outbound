"""Pydantic DTOs returned by the booking service and used by the REST API / voice tools.

Dates are ISO ``YYYY-MM-DD``; times are 24-hour ``HH:MM``. Pydantic coerces the string forms the
LLM emits into ``datetime.date`` / ``datetime.time`` automatically.
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class OptionInfo(BaseModel):
    """A bookable option (offering) that is available at a given date/time.

    ``offering_id`` is the handle the caller passes back to ``create_booking``. Never exposes who
    booked anything — only what is free.
    """

    offering_id: int
    option_name: str        # e.g. "Football", "Basketball (full court)"
    court_name: str
    sport: str
    slot_date: dt.date
    start_time: dt.time
    end_time: dt.time
    price: float = 0          # charged to non-members (INR)
    member_price: float = 0   # members book free
    sections_required: int = 1
    is_member_only: bool = False


class MemberInfo(BaseModel):
    is_member: bool
    membership_type: str | None = None
    status: str | None = None
    can_book_member_only: bool = False
    # name is intentionally NOT returned to callers (privacy). Internal use only.


class GroupCheckResult(BaseModel):
    allowed: bool
    reason: str | None = None
    group_name: str | None = None


class BookingSummary(BaseModel):
    """One row per logical booking, for the operator dashboard (names ARE shown to the operator)."""

    booking_id: int
    booking_group_id: str | None = None
    option_name: str
    sport: str
    court_name: str
    customer_name: str
    customer_phone: str
    slot_date: dt.date
    start_time: dt.time
    end_time: dt.time
    sections: list[str] = Field(default_factory=list)
    amount: float = 0
    status: str
    source: str


class BookingConfirmation(BaseModel):
    booking_id: int                    # the primary row's id
    booking_group_id: str | None = None
    option_name: str
    court_name: str
    facility_name: str
    sport: str
    slot_date: dt.date
    start_time: dt.time
    end_time: dt.time
    customer_name: str
    sections: list[str] = Field(default_factory=list)  # section labels reserved
    amount: float = 0                  # amount charged (0 for active members)
    is_member_booking: bool = False


# ---- dashboard read models (operator console) ----

class ClientInfo(BaseModel):
    """Tenant + primary-facility facts for the dashboard header and Settings page."""

    client_id: int
    name: str                       # legal name
    business_name: str              # display / spoken name
    timezone: str
    language_preference: str
    facility_name: str | None = None
    address: str | None = None
    opening_time: dt.time | None = None
    closing_time: dt.time | None = None
    slot_duration_minutes: int | None = None
    court_count: int = 0
    sports: list[str] = Field(default_factory=list)


class MemberSummary(BaseModel):
    """A member row for the operator's Members table, with booking-derived stats.

    ``spend`` sums the member's own booking amounts — note members book member-priced
    (free) slots at ₹0, so spend reflects only what they paid as a non-member-priced booking.
    ``visits`` counts every confirmed booking they hold, free or paid.
    """

    member_id: int
    name: str
    phone: str
    membership_type: str
    status: str                     # "active" | "expired" (date-derived, not the stale column)
    since: dt.date
    end_date: dt.date
    visits: int = 0
    spend: float = 0
    top_sport: str | None = None
    group_names: list[str] = Field(default_factory=list)


class OccupancyCell(BaseModel):
    start_time: dt.time
    status: str                     # "available" | "booked" | "peak" | "blocked"


class OccupancyRow(BaseModel):
    court_id: int
    court_name: str
    cells: list[OccupancyCell] = Field(default_factory=list)


class OccupancyGrid(BaseModel):
    date: dt.date
    times: list[dt.time] = Field(default_factory=list)
    rows: list[OccupancyRow] = Field(default_factory=list)


class DaySeries(BaseModel):
    date: dt.date
    label: str                      # weekday short label, e.g. "Mon"
    bookings: int = 0
    revenue: float = 0


class DashboardStats(BaseModel):
    """Aggregates for the Overview cards, weekly chart, and Reports page."""

    today: dt.date
    bookings_today: int = 0
    revenue_today: float = 0
    upcoming: int = 0               # confirmed bookings from today onward
    active_members: int = 0
    total_bookings: int = 0
    total_revenue: float = 0
    via_voice: int = 0              # bookings whose source is the voice agent
    court_count: int = 0
    series: list[DaySeries] = Field(default_factory=list)  # current week, Mon–Sun


class CallSummary(BaseModel):
    """A handled call, newest first, for the Live Calls list. Populated by the voice agent's
    call logger; empty until the agent has handled at least one call."""

    call_id: int
    caller_name: str | None = None
    caller_phone: str
    started_at: dt.datetime
    duration_seconds: int = 0
    outcome: str = "handled"        # "booked" | "handled" | "missed"
    language: str | None = None
    summary: str | None = None


class CallTurnInfo(BaseModel):
    role: str                       # "user" | "assistant"
    text: str
    ts: dt.datetime


class CallDetail(BaseModel):
    """A single call with its full transcript, for the Live Calls drill-down."""

    call_id: int
    caller_name: str | None = None
    caller_phone: str
    started_at: dt.datetime
    ended_at: dt.datetime | None = None
    duration_seconds: int = 0
    outcome: str = "handled"
    language: str | None = None
    summary: str | None = None
    turns: list[CallTurnInfo] = Field(default_factory=list)


# ---- REST / tool input models ----

class CreateBookingRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=4, max_length=20)
    offering_id: int
    date: dt.date
    time: dt.time
