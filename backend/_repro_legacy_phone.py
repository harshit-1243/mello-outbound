"""Repro: do group checks miss legacy non-normalized booking rows, and does reschedule
perpetuate the raw phone? Simulates a pre-normalization-fix row by inserting a Booking
directly with customer_phone='+919876500002' (Priya, member of 'Sunday League' with Rahul).
"""
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from tests.factory import build_world, make_memory_engine
from app.booking.service import BookingService
from app.booking import errors
from app.db.models import Booking, Slot, Section, Offering, BOOKING_CONFIRMED

T19 = dt.time(19, 0)
T20 = dt.time(20, 0)

eng = make_memory_engine()
Session = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False, future=True)
s = Session()
world = build_world(s)
svc = BookingService(s, world.client_id, today=world.D)

# --- Simulate a LEGACY booking row: Priya holds the turf at 19:00, stored with raw +91 phone
offering = s.get(Offering, world.football_off)
slot = s.scalar(
    select(Slot)
    .join(Section, Slot.section_id == Section.id)
    .where(Section.court_id == offering.court_id, Slot.slot_date == world.D,
           Slot.start_time == T19)
)
s.add(Booking(
    client_id=world.client_id, slot_id=slot.id, court_id=offering.court_id,
    section_id=slot.section_id, sport_id=offering.sport_id, offering_id=offering.id,
    booking_group_id=None, is_primary=True,
    customer_name="Priya", customer_phone="+919876500002",  # legacy format
    amount=1200, status=BOOKING_CONFIRMED, source="voice",
))
s.commit()
legacy_id = s.scalar(select(Booking.id).where(Booking.customer_phone == "+919876500002"))
print(f"legacy booking id={legacy_id} phone='+919876500002'")

# --- 1. Group one-per-timeslot check: Rahul (same group) tries the same date+time
check = svc.check_group_restriction(world.rahul, world.D, T19)
print(f"1. check_group_restriction for Rahul at same slot: allowed={check.allowed}"
      f"  (expected allowed=False if rule works; True = MISSED legacy row)")

# --- 2. Weekly cap (max 2/week for Sunday League). Legacy row should count as 1.
#    Book one more (normalized) for Priya -> group holds 2 -> a third must be blocked.
svc2 = BookingService(s, world.client_id, today=world.D)
svc2.create_booking("Priya", "9876500002", world.badminton_off, world.D, T20)
try:
    svc2.create_booking("Rahul", "9876500001", world.pickleball_off, world.D, T20)
    print("2. weekly cap: third booking SUCCEEDED -> legacy row NOT counted (cap undercounts)")
except errors.GroupRestrictionViolation as e:
    print(f"2. weekly cap: third booking blocked correctly: {e}")

# --- 3. Reschedule the legacy booking: does the new row keep the raw phone?
svc3 = BookingService(s, world.client_id, today=world.D)
conf = svc3.reschedule_booking(legacy_id, world.D + dt.timedelta(days=1), T19)
new_row = s.get(Booking, conf.booking_id)
print(f"3. rescheduled row customer_phone={new_row.customer_phone!r}"
      f"  (raw '+91...' = perpetuated; '9876500002' = normalized)")
