"""Test helpers: an isolated SQLite engine and a controlled demo 'world'.

Tenant A models the real layout's interesting cases: a Turf (football/cricket, mutually exclusive,
peak 18:00 members-only) and a Basketball Court (3 sections: Rim A / Middle / Rim C) offering
pickleball (any 1), half-court basketball (a rim), and full-court basketball (all 3). Tenant B
exists to prove tenant isolation. Hours 18:00–21:00 (three 1-hour slots) keep the dataset small.
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.booking.slotgen import generate_slots
from app.db.base import Base
from app.db import models  # noqa: F401 — register tables
from app.db.models import (
    SECTION_MIDDLE,
    SECTION_RIM,
    SECTION_STANDARD,
    Client,
    Court,
    Facility,
    Group,
    GroupMember,
    Member,
    Offering,
    Section,
    Sport,
)

# A Wednesday far in the future: the engine now refuses past-dated bookings, so the fixture
# world must stay ahead of the real clock for years (membership ranges already cover it).
WORLD_DATE = dt.date(2030, 7, 3)


def _attach_fk_pragma(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _record):  # noqa: ANN001
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def make_memory_engine() -> Engine:
    """A shared in-memory SQLite DB (StaticPool keeps one connection alive)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    _attach_fk_pragma(engine)
    Base.metadata.create_all(engine)
    return engine


def make_file_engine(path: str) -> Engine:
    """A file-backed SQLite DB with a real connection pool — used by the concurrency test so each
    thread gets its own connection. WAL + a busy timeout let writers wait (rather than error) and
    keep readers unblocked, so contention resolves on the unique index, not on lock failures."""
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record):  # noqa: ANN001
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    Base.metadata.create_all(engine)
    return engine


def build_world(session) -> SimpleNamespace:
    """Populate two tenants and return handles (ids/phones) for assertions."""
    D = WORLD_DATE

    def facility_for(client_id: int, name: str) -> Facility:
        f = Facility(client_id=client_id, name=name, opening_time=dt.time(18, 0),
                     closing_time=dt.time(21, 0), slot_duration_minutes=60)
        session.add(f)
        session.flush()
        return f

    def court_with(client_id: int, facility_id: int, name: str, sections: list[tuple[str, str]]) -> Court:
        c = Court(client_id=client_id, facility_id=facility_id, name=name)
        session.add(c)
        session.flush()
        for i, (label, kind) in enumerate(sections):
            session.add(Section(client_id=client_id, court_id=c.id, label=label, kind=kind, sort_order=i))
        session.flush()
        return c

    def offering(client_id, court, sport, name, price, req, kind) -> Offering:
        o = Offering(client_id=client_id, court_id=court.id, sport_id=sport.id, name=name,
                     price=price, sections_required=req, section_kind=kind)
        session.add(o)
        session.flush()
        return o

    # --- Tenant A ---
    a = Client(name="A Sports Pvt Ltd", business_name="Smash Arena", language_preference="hi-en")
    session.add(a)
    session.flush()
    fac = facility_for(a.id, "Smash Arena, Vashi")

    sports = {n: Sport(client_id=a.id, name=n) for n in
              ("Football", "Cricket", "Pickleball", "Basketball", "Badminton")}
    session.add_all(sports.values())
    session.flush()

    turf = court_with(a.id, fac.id, "Turf", [("Turf", SECTION_STANDARD)])
    football_off = offering(a.id, turf, sports["Football"], "Football", 1200, 1, None)
    cricket_off = offering(a.id, turf, sports["Cricket"], "Cricket", 1200, 1, None)

    bball = court_with(a.id, fac.id, "Basketball Court",
                       [("Rim A", SECTION_RIM), ("Middle", SECTION_MIDDLE), ("Rim C", SECTION_RIM)])
    pickleball_off = offering(a.id, bball, sports["Pickleball"], "Pickleball", 400, 1, None)
    bball_half_off = offering(a.id, bball, sports["Basketball"], "Basketball (3-point)", 700, 1, SECTION_RIM)
    bball_full_off = offering(a.id, bball, sports["Basketball"], "Basketball (full court)", 1000, 3, None)

    badm = court_with(a.id, fac.id, "Badminton 1", [("Badminton 1", SECTION_STANDARD)])
    badminton_off = offering(a.id, badm, sports["Badminton"], "Badminton", 500, 1, None)

    # Slots: turf peak 18:00 is members-only; everything else open.
    generate_slots(session, turf, fac, D, days=2, member_only_starts=[dt.time(18, 0)])
    generate_slots(session, bball, fac, D, days=2)
    generate_slots(session, badm, fac, D, days=2)

    active_start, active_end = dt.date(2020, 1, 1), dt.date(2099, 1, 1)
    rahul = Member(client_id=a.id, name="Rahul Sharma", phone="9876500001",
                   start_date=active_start, end_date=active_end, status="active")
    priya = Member(client_id=a.id, name="Priya Nair", phone="9876500002",
                   start_date=active_start, end_date=active_end, status="active")
    amit = Member(client_id=a.id, name="Amit Verma", phone="9876500003",
                  start_date=dt.date(2019, 1, 1), end_date=dt.date(2020, 1, 1), status="expired")
    session.add_all([rahul, priya, amit])
    session.flush()
    league = Group(client_id=a.id, name="Sunday League", max_active_per_week=2)
    session.add(league)
    session.flush()
    session.add_all([
        GroupMember(group_id=league.id, member_id=rahul.id),
        GroupMember(group_id=league.id, member_id=priya.id),
    ])

    # --- Tenant B (isolation) ---
    b = Client(name="B Sports Pvt Ltd", business_name="Other Arena")
    session.add(b)
    session.flush()
    fac_b = facility_for(b.id, "Other Arena")
    football_b = Sport(client_id=b.id, name="Football")
    session.add(football_b)
    session.flush()
    b_turf = court_with(b.id, fac_b.id, "B Turf", [("B Turf", SECTION_STANDARD)])
    b_football_off = offering(b.id, b_turf, football_b, "Football", 1000, 1, None)
    generate_slots(session, b_turf, fac_b, D, days=2)

    session.commit()

    return SimpleNamespace(
        client_id=a.id, client_b_id=b.id, D=D,
        turf_id=turf.id, bball_id=bball.id,
        football_off=football_off.id, cricket_off=cricket_off.id,
        pickleball_off=pickleball_off.id, bball_half_off=bball_half_off.id,
        bball_full_off=bball_full_off.id, badminton_off=badminton_off.id,
        b_football_off=b_football_off.id,
        rahul="9876500001", priya="9876500002", amit="9876500003", stranger="9000000000",
    )
