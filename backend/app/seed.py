"""Seed a realistic demo facility so the REST API and voice agent have data to work with.

Layout (Smash Arena):
- Turf (1 section): Football ₹1200 or Cricket ₹1200 — only one can hold a slot.
- Basketball court (3 sections: Rim A / Middle / Rim C): Pickleball ₹400 (any 1 section),
  half-court "3-point" basketball ₹700 (a rim section), full-court basketball ₹1000 (all 3).
- Tennis court (1 section): Tennis ₹600.
- Badminton: 3 separate courts (1 section each): Badminton ₹500.

Idempotent: running it again won't duplicate the demo client. Run with::

    python -m app.seed
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.booking.slotgen import generate_slots
from app.db.base import SessionLocal
from app.db.init_db import create_all
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

DEMO_BUSINESS = "Smash Arena"
SLOT_WINDOW_DAYS = 14
PEAK = [dt.time(18, 0), dt.time(19, 0), dt.time(20, 0)]  # member-only on the turf


def seed() -> None:
    create_all()
    session = SessionLocal()
    try:
        if session.scalar(select(Client).where(Client.business_name == DEMO_BUSINESS)):
            print(f"Demo client '{DEMO_BUSINESS}' already exists — nothing to do.")
            return

        client = Client(name="Smash Arena Pvt Ltd", business_name=DEMO_BUSINESS,
                        language_preference="hi-en", timezone="Asia/Kolkata")
        session.add(client)
        session.flush()

        facility = Facility(client_id=client.id, name="Smash Arena, Vashi",
                            address="Sector 17, Vashi, Navi Mumbai",
                            opening_time=dt.time(6, 0), closing_time=dt.time(23, 0),
                            slot_duration_minutes=60)
        session.add(facility)
        session.flush()

        sports = {
            n: Sport(client_id=client.id, name=n)
            for n in ("Football", "Cricket", "Pickleball", "Basketball", "Tennis", "Badminton")
        }
        session.add_all(sports.values())
        session.flush()

        def make_court(name: str, sections: list[tuple[str, str]]) -> Court:
            court = Court(client_id=client.id, facility_id=facility.id, name=name)
            session.add(court)
            session.flush()
            for i, (label, kind) in enumerate(sections):
                session.add(Section(client_id=client.id, court_id=court.id, label=label, kind=kind, sort_order=i))
            session.flush()
            return court

        def offer(court: Court, sport: str, name: str, price: int, sections_required: int, kind: str | None):
            session.add(Offering(client_id=client.id, court_id=court.id, sport_id=sports[sport].id,
                                 name=name, price=price, sections_required=sections_required,
                                 section_kind=kind))

        # 1. Turf — football or cricket, mutually exclusive (single section).
        turf = make_court("Turf", [("Turf", SECTION_STANDARD)])
        offer(turf, "Football", "Football", 1200, 1, None)
        offer(turf, "Cricket", "Cricket", 1200, 1, None)

        # 2. Basketball court — 3 sections (two rims + middle).
        bball = make_court("Basketball Court", [
            ("Rim A", SECTION_RIM), ("Middle", SECTION_MIDDLE), ("Rim C", SECTION_RIM),
        ])
        offer(bball, "Pickleball", "Pickleball", 400, 1, None)               # any 1 section
        offer(bball, "Basketball", "Basketball (3-point)", 700, 1, SECTION_RIM)   # a rim
        offer(bball, "Basketball", "Basketball (full court)", 1000, 3, None)      # all 3

        # 3. Tennis.
        tennis = make_court("Tennis Court", [("Tennis", SECTION_STANDARD)])
        offer(tennis, "Tennis", "Tennis", 600, 1, None)

        # 4. Badminton — three separate single-section courts.
        badminton_courts = [make_court(f"Badminton {i}", [(f"Badminton {i}", SECTION_STANDARD)]) for i in (1, 2, 3)]
        for bc in badminton_courts:
            offer(bc, "Badminton", "Badminton", 500, 1, None)
        session.flush()

        # Slots for the booking window. The turf's peak evening hours are members-only.
        today = dt.date.today()
        for court in (turf, bball, tennis, *badminton_courts):
            member_only = PEAK if court is turf else []
            generate_slots(session, court, facility, today, SLOT_WINDOW_DAYS, member_only)

        # Members (date-based) — two share a group so the group rules are demonstrable.
        active_start, active_end = today - dt.timedelta(days=30), today + dt.timedelta(days=335)
        rahul = Member(client_id=client.id, name="Rahul Sharma", phone="9876500001",
                       start_date=active_start, end_date=active_end, status="active")
        priya = Member(client_id=client.id, name="Priya Nair", phone="9876500002",
                       start_date=active_start, end_date=active_end, status="active")
        amit = Member(client_id=client.id, name="Amit Verma", phone="9876500003",
                      start_date=today - dt.timedelta(days=400), end_date=today - dt.timedelta(days=30),
                      status="expired")
        session.add_all([rahul, priya, amit])
        session.flush()

        league = Group(client_id=client.id, name="Sunday League", max_active_per_week=3)
        session.add(league)
        session.flush()
        session.add_all([
            GroupMember(group_id=league.id, member_id=rahul.id),
            GroupMember(group_id=league.id, member_id=priya.id),
        ])

        session.commit()
        print(f"Seeded '{DEMO_BUSINESS}' (client_id={client.id}) with 6 courts and "
              f"{SLOT_WINDOW_DAYS} days of slots.")
        print(f"Try:  GET /clients/{client.id}/availability?sport=Basketball&date={today.isoformat()}")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
