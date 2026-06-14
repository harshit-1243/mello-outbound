"""Seed a realistic spread of upcoming bookings so the operator dashboard has live data.

Runs on top of ``app.seed`` (which creates the Smash Arena facility, courts, members, and slots).
Every booking here goes through the real :class:`BookingService`, so it exercises the same rules
the voice agent does — membership pricing, the double-booking guard, group restrictions — and the
numbers on Overview / Bookings / Members / Reports are all genuinely derived, not faked.

Idempotent: a slot that's already taken is skipped, so re-running won't error or duplicate.

    python -m app.seed_demo
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.booking import errors
from app.booking.service import BookingService
from app.booking.slotgen import ensure_window
from app.db.base import SessionLocal
from app.db.models import Client

DEMO_BUSINESS = "Smash Arena"

# Members from app.seed (book member-priced = free; accrue visits).
RAHUL = "9876500001"
PRIYA = "9876500002"

# Offering ids as created by app.seed for Smash Arena:
#   1 Football(₹1200) 2 Cricket(₹1200) 3 Pickleball(₹400) 4 Basketball 3-point(₹700)
#   5 Basketball full court(₹1000) 6 Tennis(₹600) 7/8/9 Badminton(₹500, courts 1/2/3)
FOOTBALL, CRICKET, PICKLEBALL = 1, 2, 3
BBALL_HALF, BBALL_FULL, TENNIS = 4, 5, 6
BADMINTON_1, BADMINTON_2, BADMINTON_3 = 7, 8, 9

# (name, phone, offering_id, day_offset, "HH:MM", source). Members can take the turf's
# member-only evening peak (18:00–20:00); non-members are kept off it.
PLAN = [
    ("Ankit Sharma",  "9991110001", BADMINTON_1, 0, "07:00", "voice"),
    ("Sneha Kapoor",  "9991110002", TENNIS,      0, "19:00", "voice"),
    ("Rahul Sharma",  RAHUL,        FOOTBALL,    0, "18:00", "voice"),     # member · free
    ("Kush Patel",    "9991110003", BBALL_FULL,  0, "20:00", "whatsapp"),
    ("Vivek Iyer",    "9991110004", BADMINTON_2, 1, "08:00", "voice"),
    ("Neha Singh",    "9991110005", PICKLEBALL,  1, "17:00", "manual"),
    ("Priya Nair",    PRIYA,        TENNIS,      1, "20:00", "voice"),     # member · free
    ("Arjun Rao",     "9991110006", CRICKET,     2, "16:00", "voice"),
    ("Rohit Das",     "9991110007", BBALL_HALF,  2, "19:00", "voice"),
    ("Kabir Khan",    "9991110008", FOOTBALL,    3, "21:00", "voice"),     # non-peak turf
    ("Ankit Sharma",  "9991110001", BADMINTON_3, 3, "20:00", "voice"),
    ("Manan Mehta",   "9991110009", TENNIS,      4, "18:00", "manual"),
    ("Sneha Kapoor",  "9991110002", PICKLEBALL,  4, "19:00", "voice"),
    ("Rahul Sharma",  RAHUL,        BADMINTON_1, 5, "07:00", "voice"),     # member · free
]


def seed_demo() -> None:
    session = SessionLocal()
    try:
        client = session.scalar(select(Client).where(Client.business_name == DEMO_BUSINESS))
        if client is None:
            print(f"No '{DEMO_BUSINESS}' client found — run `python -m app.seed` first.")
            return

        # Make sure the next two weeks of slots exist so today-onward bookings have somewhere to go.
        ensure_window(session, client.id, days=14)

        svc = BookingService(session, client.id)
        today = dt.date.today()
        booked = skipped = 0
        for name, phone, offering_id, offset, hhmm, source in PLAN:
            date = today + dt.timedelta(days=offset)
            time = dt.datetime.strptime(hhmm, "%H:%M").time()
            try:
                svc.create_booking(name, phone, offering_id, date, time, source=source)
                booked += 1
            except errors.BookingError as exc:
                skipped += 1
                print(f"  skip {name} {date} {hhmm}: {exc.message}")

        print(f"Demo bookings: {booked} created, {skipped} skipped (client_id={client.id}).")
    finally:
        session.close()


if __name__ == "__main__":
    seed_demo()
