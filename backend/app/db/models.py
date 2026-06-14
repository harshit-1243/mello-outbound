"""ORM models for the Mello booking engine.

Multi-tenant: every tenant-owned row carries ``client_id`` (denormalized onto courts, sections,
slots, bookings, members, groups) so queries filter cheaply and Postgres Row-Level Security can
isolate tenants with a single predicate. See ``app/db/migrations/001_enable_rls.sql``.

Resource model — sections are the atomic bookable unit:
- A ``Court`` is a physical space made of one or more ``Section`` rows (a turf has 1 section; a
  basketball court has 3 — two "rim" ends + a "middle"; each badminton court is its own 1-section
  court).
- An ``Offering`` is a bookable option on a court: a sport, a price, how many sections it needs,
  and (optionally) which *kind* of section. Football/Cricket each take the turf's 1 section (so
  they're mutually exclusive); pickleball takes any 1 of 3; half-court ("3-point") basketball takes
  1 *rim*; full-court basketball takes all 3.
- A ``Slot`` is a time block on ONE section. A ``Booking`` references exactly one section-slot, so
  the partial unique index on ``bookings(slot_id) WHERE status='confirmed'`` still makes a
  double-booking impossible at the DB level — on both SQLite and Postgres, even under a race.
- A booking that spans several sections (full-court basketball) is several Booking rows sharing a
  ``booking_group_id``, inserted in one transaction: if any section is taken, the whole group is
  rejected by the unique index. The ``is_primary`` row carries the price; the rest carry 0.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Status / enum-like string values (kept as plain strings for SQLite/Postgres portability).
BOOKING_CONFIRMED = "confirmed"
BOOKING_CANCELLED = "cancelled"

MEMBER_ACTIVE = "active"
MEMBER_EXPIRED = "expired"

SLOT_AVAILABLE = "available"
SLOT_BLOCKED = "blocked"  # admin-blocked (maintenance, private event)

# Call outcomes + transcript roles (plain strings for SQLite/Postgres portability, like BOOKING_*).
CALL_BOOKED = "booked"
CALL_HANDLED = "handled"
CALL_MISSED = "missed"
CALL_ROLE_USER = "user"
CALL_ROLE_ASSISTANT = "assistant"

# Section kinds. "standard" = a plain single section (turf, tennis, badminton court). "rim" /
# "middle" describe a basketball court's three parts; half-court basketball needs a "rim".
SECTION_STANDARD = "standard"
SECTION_RIM = "rim"
SECTION_MIDDLE = "middle"

# Allocation preference: lower = picked first. Filling "middle" before "rim" keeps the rim ends
# open for half-court basketball as long as possible.
_KIND_PRIORITY = {SECTION_MIDDLE: 0, SECTION_STANDARD: 1, SECTION_RIM: 2}


class Client(Base):
    """A SaaS tenant — one facility operator / business."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    business_name: Mapped[str] = mapped_column(String(200), nullable=False)  # spoken on calls
    language_preference: Mapped[str] = mapped_column(String(20), default="hi-en")
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    facilities: Mapped[list["Facility"]] = relationship(back_populates="client")


class Facility(Base):
    """A physical venue belonging to a client."""

    __tablename__ = "facilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str] = mapped_column(String(400), default="")
    opening_time: Mapped[dt.time] = mapped_column(Time, default=dt.time(6, 0))
    closing_time: Mapped[dt.time] = mapped_column(Time, default=dt.time(23, 0))
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    client: Mapped[Client] = relationship(back_populates="facilities")
    courts: Mapped[list["Court"]] = relationship(back_populates="facility")


class Sport(Base):
    """A sport / service a client offers (e.g. Football, Cricket, Pickleball, Basketball)."""

    __tablename__ = "sports"
    __table_args__ = (UniqueConstraint("client_id", "name", name="uq_sport_client_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class Court(Base):
    """A physical bookable space within a facility, composed of one or more sections.

    A court no longer maps to a single sport — what can be booked on it is described by its
    ``Offering`` rows. A turf is one section; a basketball court is three.
    """

    __tablename__ = "courts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    facility: Mapped[Facility] = relationship(back_populates="courts")
    sections: Mapped[list["Section"]] = relationship(back_populates="court", order_by="Section.sort_order")
    offerings: Mapped[list["Offering"]] = relationship(back_populates="court")


class Section(Base):
    """The smallest bookable physical unit of a court. Bookings reserve sections."""

    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(50), nullable=False)        # e.g. "Rim A", "Middle"
    kind: Mapped[str] = mapped_column(String(20), default=SECTION_STANDARD)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    court: Mapped[Court] = relationship(back_populates="sections")

    @property
    def alloc_priority(self) -> tuple[int, int]:
        """Ordering key for allocation: middle < standard < rim, then by sort_order."""
        return (_KIND_PRIORITY.get(self.kind, 1), self.sort_order)


class Offering(Base):
    """A bookable option on a court: a sport at a price, consuming N sections of a given kind.

    ``sections_required`` is how many sections the option occupies; ``section_kind`` (nullable)
    restricts *which* sections qualify (e.g. half-court basketball must use a 'rim'). A "whole
    court" option simply requires as many sections as the court has.
    """

    __tablename__ = "offerings"
    __table_args__ = (UniqueConstraint("court_id", "name", name="uq_offering_court_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id"), nullable=False, index=True)
    sport_id: Mapped[int] = mapped_column(ForeignKey("sports.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)        # e.g. "Basketball (full court)"
    price: Mapped[float] = mapped_column(Numeric(10, 2), default=0)        # charged to non-members
    sections_required: Mapped[int] = mapped_column(Integer, default=1)
    section_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)  # None = any kind

    court: Mapped[Court] = relationship(back_populates="offerings")
    sport: Mapped[Sport] = relationship()


class Slot(Base):
    """A concrete bookable time block on a single section.

    Generated from the facility's operating hours + slot duration. ``is_member_only`` implements
    the "membership priority slot reservation": such slots require an active member.
    """

    __tablename__ = "slots"
    __table_args__ = (
        UniqueConstraint("section_id", "slot_date", "start_time", name="uq_slot_section_datetime"),
        Index("ix_slot_lookup", "client_id", "slot_date", "start_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id"), nullable=False, index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False, index=True)
    slot_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    start_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    end_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    is_member_only: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default=SLOT_AVAILABLE)

    section: Mapped[Section] = relationship()
    court: Mapped[Court] = relationship()
    bookings: Mapped[list["Booking"]] = relationship(back_populates="slot")


class Booking(Base):
    """A confirmed (or cancelled) booking of one section-slot.

    The partial unique index guarantees at most one *confirmed* booking per section-slot. A booking
    spanning several sections (full-court basketball) is several rows sharing ``booking_group_id``;
    the ``is_primary`` row holds the price (others hold 0) so revenue never double-counts.
    """

    __tablename__ = "bookings"
    __table_args__ = (
        Index(
            "uq_booking_active_slot",
            "slot_id",
            unique=True,
            sqlite_where=text("status = 'confirmed'"),
            postgresql_where=text("status = 'confirmed'"),
        ),
        Index("ix_booking_phone", "client_id", "customer_phone"),
        Index("ix_booking_group", "booking_group_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"), nullable=False, index=True)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id"), nullable=False)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    sport_id: Mapped[int] = mapped_column(ForeignKey("sports.id"), nullable=False)
    offering_id: Mapped[int] = mapped_column(ForeignKey("offerings.id"), nullable=False)
    # Groups the rows of a multi-section booking; NULL for single-section bookings.
    booking_group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Exactly one row per logical booking is primary — it carries the price and represents the
    # booking in listings / weekly-cap counts.
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)  # full price on primary, 0 else
    status: Mapped[str] = mapped_column(String(20), default=BOOKING_CONFIRMED)
    source: Mapped[str] = mapped_column(String(20), default="voice")  # voice | whatsapp | manual
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    slot: Mapped[Slot] = relationship(back_populates="bookings")
    offering: Mapped[Offering] = relationship()


class Member(Base):
    """A facility member. Membership is keyed by phone number within a client.

    Membership validity is *date-based*: a member is active when ``start_date <= today <= end_date``.
    ``is_active(today)`` is the single source of truth — the stored ``status`` column is a cached
    label for display/listing and is kept in sync by the service, but rules never trust it directly.
    """

    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("client_id", "phone", name="uq_member_client_phone"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    membership_type: Mapped[str] = mapped_column(String(50), default="standard")
    # Date-based lifecycle. start_date defaults to join day; end_date is the expiry.
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False, default=dt.date.today)
    end_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=MEMBER_ACTIVE)  # cached label; see is_active
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    group_links: Mapped[list["GroupMember"]] = relationship(back_populates="member")

    def is_active(self, today: dt.date) -> bool:
        """True iff the membership covers ``today`` (auto-expiry, no manual flip needed)."""
        return self.start_date <= today <= self.end_date


class Group(Base):
    """A group whose members share a cross-booking restriction."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Default rule: at most one confirmed booking per (date, start_time) across the whole group.
    restriction_type: Mapped[str] = mapped_column(String(50), default="one_per_timeslot")
    # Optional shared quota: max logical bookings the whole group may hold in one calendar
    # week (Mon–Sun). NULL = no weekly cap (only the per-timeslot rule applies).
    max_active_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    members: Mapped[list["GroupMember"]] = relationship(back_populates="group")


class GroupMember(Base):
    """Membership link between a Group and a Member."""

    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "member_id", name="uq_group_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False, index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)

    group: Mapped[Group] = relationship(back_populates="members")
    member: Mapped[Member] = relationship(back_populates="group_links")


class Call(Base):
    """One handled call (browser harness now; Exotel phone call in M3). Feeds the Live Calls page.

    The voice agent writes a Call row + its CallTurn transcript when the call ends, so the operator
    can review conversations on the dashboard instead of reading server logs.
    """

    __tablename__ = "calls"
    __table_args__ = (Index("ix_call_client_started", "client_id", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    caller_phone: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    caller_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[str] = mapped_column(String(20), default=CALL_HANDLED)  # booked | handled | missed
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    turns: Mapped[list["CallTurn"]] = relationship(
        back_populates="call", order_by="CallTurn.ts, CallTurn.id", cascade="all, delete-orphan"
    )


class CallTurn(Base):
    """One utterance in a call transcript (caller or agent), in arrival order."""

    __tablename__ = "call_turns"
    __table_args__ = (Index("ix_call_turn_call", "call_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), nullable=False, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    text: Mapped[str] = mapped_column(String, nullable=False)      # untruncated (TEXT on both backends)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    call: Mapped[Call] = relationship(back_populates="turns")
