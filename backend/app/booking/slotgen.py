"""Generate concrete bookable slots — one per section, per time block — for a court.

Used by the seed script and tests. In production a daily job (``ensure_window``) calls this to roll
the booking window forward; the dashboard can also regenerate after hours/duration changes.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SLOT_AVAILABLE, Court, Facility, Slot

_ANCHOR = dt.date(2000, 1, 1)  # arbitrary date for time arithmetic


def iter_time_blocks(
    opening: dt.time, closing: dt.time, duration_min: int
) -> Iterator[tuple[dt.time, dt.time]]:
    """Yield (start, end) time pairs from opening to closing in fixed steps."""
    step = dt.timedelta(minutes=duration_min)
    cur = dt.datetime.combine(_ANCHOR, opening)
    limit = dt.datetime.combine(_ANCHOR, closing)
    while cur + step <= limit:
        yield cur.time(), (cur + step).time()
        cur += step


def generate_slots(
    session: Session,
    court: Court,
    facility: Facility,
    start_date: dt.date,
    days: int,
    member_only_starts: Iterable[dt.time] = (),
) -> list[Slot]:
    """Create slots for every section of ``court`` for ``days`` days from ``start_date``.

    Skips (section, date, start_time) combinations that already exist, so it is safe to re-run.
    """
    member_only = set(member_only_starts)
    created: list[Slot] = []
    for section in court.sections:
        existing = {
            (s.slot_date, s.start_time)
            for s in session.scalars(select(Slot).where(Slot.section_id == section.id))
        }
        for offset in range(days):
            day = start_date + dt.timedelta(days=offset)
            for start, end in iter_time_blocks(
                facility.opening_time, facility.closing_time, facility.slot_duration_minutes
            ):
                if (day, start) in existing:
                    continue
                slot = Slot(
                    client_id=court.client_id,
                    court_id=court.id,
                    section_id=section.id,
                    slot_date=day,
                    start_time=start,
                    end_time=end,
                    is_member_only=start in member_only,
                    status=SLOT_AVAILABLE,
                )
                session.add(slot)
                created.append(slot)
    return created


def _member_only_pattern(session: Session, court: Court) -> set[dt.time]:
    """Infer which start-times are member-only for a court from its existing slots, so a rolling
    refresh preserves the member-only designation set at seed/config time without extra schema."""
    return set(
        session.scalars(
            select(Slot.start_time)
            .where(Slot.court_id == court.id, Slot.is_member_only.is_(True))
            .distinct()
        ).all()
    )


def ensure_window(
    session: Session,
    client_id: int,
    days: int = 14,
    start_date: dt.date | None = None,
    commit: bool = True,
) -> int:
    """Idempotently ensure the next ``days`` days of slots exist for every court of a client.

    This is the production "rolling window" job: run it daily and it tops up missing days while
    leaving existing slots (and their bookings) untouched. Returns the number of slots created.
    """
    start = start_date or dt.date.today()
    facilities = {
        f.id: f for f in session.scalars(select(Facility).where(Facility.client_id == client_id))
    }
    total = 0
    for court in session.scalars(select(Court).where(Court.client_id == client_id)):
        facility = facilities.get(court.facility_id)
        if facility is None:
            continue
        created = generate_slots(
            session, court, facility, start, days, _member_only_pattern(session, court)
        )
        total += len(created)
    if commit:
        session.commit()
    return total


if __name__ == "__main__":
    # Daily rolling-window refresh for every client. Wire this to Supabase cron in production.
    from app.db.base import SessionLocal
    from app.db.models import Client

    db = SessionLocal()
    try:
        grand_total = 0
        for cid in db.scalars(select(Client.id)).all():
            n = ensure_window(db, cid, days=14)
            grand_total += n
            print(f"client {cid}: +{n} slots")
        print(f"Done. {grand_total} slots created across all clients.")
    finally:
        db.close()
