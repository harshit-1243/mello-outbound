"""Show bookings written to the database.

    python -m app.show_bookings            # all bookings, newest first
    python -m app.show_bookings voice      # only bookings made by the voice agent
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Booking, Court, Offering, Slot


def main() -> None:
    source_filter = sys.argv[1] if len(sys.argv) > 1 else None

    db = SessionLocal()
    try:
        # One line per logical booking (the primary row); a full-court booking is one line, not 3.
        stmt = (
            select(Booking, Slot, Court, Offering)
            .join(Slot, Booking.slot_id == Slot.id)
            .join(Court, Booking.court_id == Court.id)
            .join(Offering, Booking.offering_id == Offering.id)
            .where(Booking.is_primary.is_(True))
            .order_by(Booking.created_at.desc())
        )
        if source_filter:
            stmt = stmt.where(Booking.source == source_filter)

        rows = db.execute(stmt).all()
        if not rows:
            print("No bookings found" + (f" with source={source_filter!r}." if source_filter else "."))
            return

        print(f"{len(rows)} booking(s) (newest first):\n")
        for b, s, c, o in rows:
            amount = f"₹{float(b.amount):.0f}" if float(b.amount) else "free"
            print(
                f"#{b.id}  [{b.status}]  {c.name:<16} {o.name:<24} "
                f"{s.slot_date} {s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}  "
                f"{amount:>6}  | {b.customer_name} ({b.customer_phone})  via {b.source}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
