"""BookingService — the operations the voice agent calls, plus the rules that protect them.

Every instance is scoped to a single ``client_id`` (the tenant). All queries filter by it, so a
service for client A can never read or write client B's data, mirroring the Postgres RLS policy.

Resource model: a court is made of sections; an *offering* (sport option) consumes one or more
sections of a given kind. Availability and booking are therefore about allocating sections:

- ``check_availability`` returns the bookable *options* (offerings) free at a date/time.
- ``create_booking`` allocates the offering's sections (middle-first, so rim ends stay open for
  half-court basketball), writes one Booking row per section, and is protected by the partial
  unique index on ``bookings(slot_id) WHERE status='confirmed'``. A multi-section booking is
  several rows committed together: if any section was taken, the index aborts the whole booking.
"""
from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.booking import errors
from app.booking.schemas import (
    BookingConfirmation,
    BookingSummary,
    CallDetail,
    CallSummary,
    CallTurnInfo,
    ClientInfo,
    DashboardStats,
    DaySeries,
    GroupCheckResult,
    MemberInfo,
    MemberSummary,
    OccupancyCell,
    OccupancyGrid,
    OccupancyRow,
    OptionInfo,
)
from app.booking.util import normalize_phone
from app.db.models import (
    BOOKING_CANCELLED,
    BOOKING_CONFIRMED,
    MEMBER_ACTIVE,
    MEMBER_EXPIRED,
    SLOT_AVAILABLE,
    Booking,
    Call,
    CallTurn,
    Client,
    Court,
    Facility,
    Group,
    GroupMember,
    Member,
    Offering,
    Section,
    Slot,
    Sport,
)

# Look this many days ahead when searching for the "next available" option.
NEXT_SLOT_SEARCH_DAYS = 7


class BookingService:
    def __init__(
        self,
        session: Session,
        client_id: int,
        today: dt.date | None = None,
        now: dt.datetime | None = None,
    ):
        self.session = session
        self.client_id = client_id
        # Reference clock for "is this in the past" and membership validity. Defaults to the
        # real now in the client's timezone; tests pass a fixed today/now for determinism.
        # When only `today` is given (tests), time-of-day checks are skipped.
        if now is None and today is None:
            now = self._client_now()
        self.now = now
        self.today = today or now.date()

    def _client_now(self) -> dt.datetime:
        """Wall-clock now in the client's timezone (falls back to IST)."""
        tzname = "Asia/Kolkata"
        client = self.session.get(Client, self.client_id)
        if client is not None and client.timezone:
            tzname = client.timezone
        try:
            tz = ZoneInfo(tzname)
        except (KeyError, ValueError):
            tz = ZoneInfo("Asia/Kolkata")
        return dt.datetime.now(tz)

    def _is_past(self, date: dt.date, time: dt.time | None = None) -> bool:
        if date < self.today:
            return True
        return (
            date == self.today
            and time is not None
            and self.now is not None
            and time <= self.now.time()
        )

    # ---- 1. availability -------------------------------------------------

    def check_availability(
        self, sport: str, date: dt.date, time: dt.time | None = None
    ) -> list[OptionInfo]:
        """Bookable options for a sport on a date (optionally at a specific start time).

        A sport may have several options (e.g. half-court vs full-court basketball); each is
        returned separately with its price. Never returns customer identities. Slots in the
        past (earlier dates, or earlier today) are never offered.
        """
        if date < self.today:
            return []
        options: list[OptionInfo] = []
        for offering in self._offerings_for_sport(sport):
            free = self._free_section_slots(offering.court_id, date, offering.section_kind, time)
            by_time: dict[dt.time, list[Slot]] = {}
            for s in free:
                by_time.setdefault(s.start_time, []).append(s)
            for start_time, slots in sorted(by_time.items()):
                if self._is_past(date, start_time):
                    continue
                if len(slots) < offering.sections_required:
                    continue
                chosen = self._allocate(slots, offering.sections_required)
                options.append(self._option_info(offering, chosen))
        options.sort(key=lambda o: (o.start_time, o.court_name, o.option_name))
        return options

    # ---- 2. membership ---------------------------------------------------

    def verify_member(self, phone: str) -> MemberInfo:
        member = self._find_member(phone)
        if member is None:
            return MemberInfo(is_member=False, can_book_member_only=False)
        active = member.is_active(self.today)  # date-based: auto-expires, ignores stale status
        return MemberInfo(
            is_member=True,
            membership_type=member.membership_type,
            status=MEMBER_ACTIVE if active else MEMBER_EXPIRED,
            can_book_member_only=active,
        )

    # ---- 3. group restriction -------------------------------------------

    def check_group_restriction(self, phone: str, date: dt.date, time: dt.time) -> GroupCheckResult:
        """Block if another member of the caller's group already holds the same date+time."""
        member = self._find_member(phone)
        if member is None:
            return GroupCheckResult(allowed=True)

        group_links = self.session.scalars(
            select(GroupMember).where(GroupMember.member_id == member.id)
        ).all()
        for link in group_links:
            group = link.group
            other_ids = [gm.member_id for gm in group.members if gm.member_id != member.id]
            if not other_ids:
                continue
            other_phones = self.session.scalars(
                select(Member.phone).where(Member.id.in_(other_ids))
            ).all()
            if not other_phones:
                continue
            # Compare in normalized form on BOTH sides: bookings store normalized phones
            # (see create_booking), but member rows may carry +91/spaced formats.
            normalized_others = {normalize_phone(p) for p in other_phones}
            conflict = self.session.scalar(
                select(Booking.id)
                .join(Slot, Booking.slot_id == Slot.id)
                .where(
                    Booking.client_id == self.client_id,
                    Booking.status == BOOKING_CONFIRMED,
                    Booking.customer_phone.in_(normalized_others),
                    Slot.slot_date == date,
                    Slot.start_time == time,
                )
                .limit(1)
            )
            if conflict is not None:
                return GroupCheckResult(
                    allowed=False,
                    group_name=group.name,
                    reason=(
                        f"Another member of group '{group.name}' already has a booking at "
                        f"{time.strftime('%H:%M')} on {date.isoformat()}."
                    ),
                )
        return GroupCheckResult(allowed=True)

    def _check_group_weekly_cap(self, phone: str, date: dt.date) -> GroupCheckResult:
        """Block if any of the caller's groups would exceed its weekly booking quota.

        Counts *logical* bookings (primary rows) held by all the group's members within the
        calendar week (Mon–Sun) containing ``date``.
        """
        member = self._find_member(phone)
        if member is None:
            return GroupCheckResult(allowed=True)

        week_start = date - dt.timedelta(days=date.weekday())
        week_end = week_start + dt.timedelta(days=6)

        for link in self.session.scalars(
            select(GroupMember).where(GroupMember.member_id == member.id)
        ).all():
            group = link.group
            if group.max_active_per_week is None:
                continue
            phones = self.session.scalars(
                select(Member.phone).where(
                    Member.id.in_([gm.member_id for gm in group.members])
                )
            ).all()
            if not phones:
                continue
            normalized_phones = {normalize_phone(p) for p in phones}
            held = self.session.scalar(
                select(func.count(Booking.id))
                .join(Slot, Booking.slot_id == Slot.id)
                .where(
                    Booking.client_id == self.client_id,
                    Booking.status == BOOKING_CONFIRMED,
                    Booking.is_primary.is_(True),
                    Booking.customer_phone.in_(normalized_phones),
                    Slot.slot_date >= week_start,
                    Slot.slot_date <= week_end,
                )
            ) or 0
            if held >= group.max_active_per_week:
                return GroupCheckResult(
                    allowed=False,
                    group_name=group.name,
                    reason=(
                        f"Group '{group.name}' has reached its limit of "
                        f"{group.max_active_per_week} bookings for the week of "
                        f"{week_start.isoformat()}."
                    ),
                )
        return GroupCheckResult(allowed=True)

    # ---- 4. create booking ----------------------------------------------

    def create_booking(
        self,
        name: str,
        phone: str,
        offering_id: int,
        date: dt.date,
        time: dt.time,
        source: str = "voice",
    ) -> BookingConfirmation:
        name, phone = self._validate_customer(name, phone)
        if self._is_past(date, time):
            raise errors.SlotUnavailable("That time has already passed.")
        offering = self.session.get(Offering, offering_id)
        if offering is None or offering.client_id != self.client_id:
            raise errors.SlotNotFound("No such bookable option.")

        free = self._free_section_slots(
            offering.court_id, date, offering.section_kind, time, lock=True
        )
        if not free:
            # Distinguish "nothing exists at that time" from "all taken".
            any_slot = self.session.scalar(
                select(Slot.id)
                .join(Section, Slot.section_id == Section.id)
                .where(Section.court_id == offering.court_id, Slot.slot_date == date,
                       Slot.start_time == time)
                .limit(1)
            )
            if any_slot is None:
                raise errors.SlotNotFound("No such slot exists for that option, date, and time.")
            raise errors.SlotUnavailable("That option is no longer available at that time.")
        if len(free) < offering.sections_required:
            raise errors.SlotUnavailable("That option is no longer available at that time.")

        chosen = self._allocate(free, offering.sections_required)
        is_member, amount = self._check_rules_and_price(offering, chosen, phone, date, time)
        self._insert_rows(offering, chosen, name, phone, source, amount)
        try:
            self.session.commit()
        except IntegrityError:
            # Lost a race for one of the sections — the partial unique index rejected the duplicate.
            self.session.rollback()
            raise errors.SlotUnavailable("That slot was just taken by another caller.")

        primary = self.session.scalar(
            select(Booking).where(
                Booking.slot_id == chosen[0].id, Booking.status == BOOKING_CONFIRMED
            )
        )
        return self._confirmation(offering, chosen, primary, amount, is_member)

    # ---- 6. dashboard: list / cancel / reschedule ------------------------

    def list_bookings(self, include_cancelled: bool = False) -> list[BookingSummary]:
        """All logical bookings (one row per booking) for the operator dashboard, in date order."""
        stmt = (
            select(Booking, Slot, Offering, Court)
            .join(Slot, Booking.slot_id == Slot.id)
            .join(Offering, Booking.offering_id == Offering.id)
            .join(Court, Booking.court_id == Court.id)
            .where(Booking.client_id == self.client_id, Booking.is_primary.is_(True))
            .order_by(Slot.slot_date, Slot.start_time, Booking.id)
        )
        if not include_cancelled:
            stmt = stmt.where(Booking.status == BOOKING_CONFIRMED)
        return [self._summary(*row) for row in self.session.execute(stmt).all()]

    def _summary(self, booking: Booking, slot: Slot, offering: Offering, court: Court) -> BookingSummary:
        return BookingSummary(
            booking_id=booking.id,
            booking_group_id=booking.booking_group_id,
            option_name=offering.name,
            sport=offering.sport.name,
            court_name=court.name,
            customer_name=booking.customer_name,
            customer_phone=booking.customer_phone,
            slot_date=slot.slot_date,
            start_time=slot.start_time,
            end_time=slot.end_time,
            sections=self._group_section_labels(booking),
            amount=float(booking.amount or 0),
            status=booking.status,
            source=booking.source,
        )

    # ---- 7. caller-owned operations (voice: "cancel my booking") ----------

    def _owned_rows_for_phone(self, phone: str) -> list[tuple]:
        """Upcoming confirmed primary rows owned by this phone (normalized match).

        Matching is done in Python so bookings stored before phone normalization
        (or member rows in odd formats) still match.
        """
        target = normalize_phone(phone or "")
        if not target:
            return []
        rows = self.session.execute(
            select(Booking, Slot, Offering, Court)
            .join(Slot, Booking.slot_id == Slot.id)
            .join(Offering, Booking.offering_id == Offering.id)
            .join(Court, Booking.court_id == Court.id)
            .where(
                Booking.client_id == self.client_id,
                Booking.is_primary.is_(True),
                Booking.status == BOOKING_CONFIRMED,
                Slot.slot_date >= self.today,
            )
            .order_by(Slot.slot_date, Slot.start_time)
        ).all()
        return [r for r in rows if normalize_phone(r[0].customer_phone) == target]

    def find_bookings_for_phone(self, phone: str) -> list[BookingSummary]:
        """The caller's own upcoming bookings. Never exposes anyone else's."""
        return [self._summary(*row) for row in self._owned_rows_for_phone(phone)]

    def _owned_primary_for_phone(
        self, phone: str, date: dt.date, time: dt.time | None
    ) -> Booking:
        matches = [
            row for row in self._owned_rows_for_phone(phone)
            if row[1].slot_date == date and (time is None or row[1].start_time == time)
        ]
        if not matches:
            raise errors.SlotNotFound(
                "No upcoming booking found for that phone number on that date."
            )
        if len(matches) > 1:
            times = ", ".join(r[1].start_time.strftime("%H:%M") for r in matches)
            raise errors.InvalidInput(
                f"That number has several bookings that day (at {times}) — which time?"
            )
        return matches[0][0]

    def cancel_booking_for_phone(
        self, phone: str, date: dt.date, time: dt.time | None = None
    ) -> BookingSummary:
        """Cancel the caller's own booking, located by phone + date (+ time if ambiguous)."""
        primary = self._owned_primary_for_phone(phone, date, time)
        summary = self._summary(
            primary,
            self.session.get(Slot, primary.slot_id),
            self.session.get(Offering, primary.offering_id),
            self.session.get(Court, primary.court_id),
        )
        self.cancel_booking(primary.id)
        summary.status = BOOKING_CANCELLED
        return summary

    def reschedule_booking_for_phone(
        self,
        phone: str,
        date: dt.date,
        time: dt.time | None,
        new_date: dt.date,
        new_time: dt.time,
    ) -> BookingConfirmation:
        """Move the caller's own booking, located by phone + date (+ time if ambiguous)."""
        primary = self._owned_primary_for_phone(phone, date, time)
        return self.reschedule_booking(primary.id, new_date, new_time)

    def cancel_booking(self, booking_id: int) -> None:
        """Cancel a booking (and every section row of its group), freeing the slots."""
        primary = self._owned_primary(booking_id)
        for row in self._group_rows(primary):
            row.status = BOOKING_CANCELLED
        self.session.commit()

    def reschedule_booking(
        self, booking_id: int, new_date: dt.date, new_time: dt.time
    ) -> BookingConfirmation:
        """Move a booking to a new date/time, re-allocating its sections atomically.

        The old rows are cancelled and new ones created in a single transaction: if the new time
        can't fit the option, nothing changes and an error is raised.
        """
        if self._is_past(new_date, new_time):
            raise errors.SlotUnavailable("That time has already passed.")
        primary = self._owned_primary(booking_id)
        offering = self.session.get(Offering, primary.offering_id)
        name, phone, source = primary.customer_name, primary.customer_phone, primary.source

        # Cancel the old rows first (within this transaction) so the new-time rule checks and
        # availability don't count the booking against itself.
        for row in self._group_rows(primary):
            row.status = BOOKING_CANCELLED
        self.session.flush()

        free = self._free_section_slots(offering.court_id, new_date, offering.section_kind, new_time, lock=True)
        if len(free) < offering.sections_required:
            self.session.rollback()
            raise errors.SlotUnavailable("That option is not available at the new time.")
        chosen = self._allocate(free, offering.sections_required)
        is_member, amount = self._check_rules_and_price(offering, chosen, phone, new_date, new_time)
        self._insert_rows(offering, chosen, name, phone, source, amount)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise errors.SlotUnavailable("That slot was just taken by another caller.")

        new_primary = self.session.scalar(
            select(Booking).where(Booking.slot_id == chosen[0].id, Booking.status == BOOKING_CONFIRMED)
        )
        return self._confirmation(offering, chosen, new_primary, amount, is_member)

    # ---- 5. next available ----------------------------------------------

    def get_next_available_slot(self, sport: str, date: dt.date) -> OptionInfo | None:
        """Earliest available option for a sport from ``date`` onward (up to a week ahead)."""
        start = max(date, self.today)  # never search the past
        for offset in range(NEXT_SLOT_SEARCH_DAYS + 1):
            day = start + dt.timedelta(days=offset)
            opts = self.check_availability(sport, day)
            if opts:
                return opts[0]
        return None

    # ---- 8. dashboard reads (operator console) --------------------------

    def get_client_info(self) -> ClientInfo:
        """Tenant + primary-facility facts for the header and Settings page."""
        client = self.session.get(Client, self.client_id)
        if client is None:
            raise errors.SlotNotFound("No such client.")
        facility = self.session.scalars(
            select(Facility).where(Facility.client_id == self.client_id).order_by(Facility.id)
        ).first()
        court_count = self.session.scalar(
            select(func.count(Court.id)).where(Court.client_id == self.client_id)
        ) or 0
        sports = list(self.session.scalars(
            select(Sport.name).where(Sport.client_id == self.client_id).order_by(Sport.name)
        ))
        return ClientInfo(
            client_id=client.id,
            name=client.name,
            business_name=client.business_name,
            timezone=client.timezone,
            language_preference=client.language_preference,
            facility_name=facility.name if facility else None,
            address=facility.address if facility else None,
            opening_time=facility.opening_time if facility else None,
            closing_time=facility.closing_time if facility else None,
            slot_duration_minutes=facility.slot_duration_minutes if facility else None,
            court_count=int(court_count),
            sports=sports,
        )

    def list_members(self) -> list[MemberSummary]:
        """Every member with booking-derived stats (visits, spend, favourite sport, groups)."""
        members = list(self.session.scalars(
            select(Member).where(Member.client_id == self.client_id).order_by(Member.name)
        ))

        # All confirmed primary bookings, bucketed by normalized phone, so each member's
        # visits/spend/top-sport come from one pass instead of a query per member.
        booking_rows = self.session.execute(
            select(Booking.customer_phone, Booking.amount, Sport.name)
            .join(Sport, Booking.sport_id == Sport.id)
            .where(
                Booking.client_id == self.client_id,
                Booking.is_primary.is_(True),
                Booking.status == BOOKING_CONFIRMED,
            )
        ).all()
        by_phone: dict[str, list[tuple[float, str]]] = {}
        for phone, amount, sport_name in booking_rows:
            by_phone.setdefault(normalize_phone(phone), []).append((float(amount or 0), sport_name))

        # Group memberships, member_id -> [group names].
        member_groups: dict[int, list[str]] = {}
        for member_id, group_name in self.session.execute(
            select(GroupMember.member_id, Group.name)
            .join(Group, GroupMember.group_id == Group.id)
            .where(Group.client_id == self.client_id)
        ).all():
            member_groups.setdefault(member_id, []).append(group_name)

        summaries: list[MemberSummary] = []
        for m in members:
            mine = by_phone.get(normalize_phone(m.phone), [])
            top_sport = None
            if mine:
                counts: dict[str, int] = {}
                for _, sport_name in mine:
                    counts[sport_name] = counts.get(sport_name, 0) + 1
                top_sport = max(counts, key=counts.get)
            summaries.append(MemberSummary(
                member_id=m.id,
                name=m.name,
                phone=m.phone,
                membership_type=m.membership_type,
                status=MEMBER_ACTIVE if m.is_active(self.today) else MEMBER_EXPIRED,
                since=m.start_date,
                end_date=m.end_date,
                visits=len(mine),
                spend=sum(a for a, _ in mine),
                top_sport=top_sport,
                group_names=member_groups.get(m.id, []),
            ))
        return summaries

    def get_occupancy(self, date: dt.date) -> OccupancyGrid:
        """Per-court occupancy across 2-hour buckets of the operating window.

        Cell status: ``booked`` (a confirmed booking touches the court at that hour),
        ``peak`` (a member-only slot is still free), ``available`` (free), or ``blocked``
        (admin-blocked or outside the operating window).
        """
        facility = self.session.scalars(
            select(Facility).where(Facility.client_id == self.client_id).order_by(Facility.id)
        ).first()
        open_h = facility.opening_time.hour if facility else 6
        close_h = facility.closing_time.hour if facility else 23
        times = [dt.time(h, 0) for h in range(open_h, close_h, 2)]  # 2-hourly → ~9 columns

        courts = list(self.session.scalars(
            select(Court).where(Court.client_id == self.client_id).order_by(Court.id)
        ))
        slots = list(self.session.scalars(
            select(Slot).where(Slot.client_id == self.client_id, Slot.slot_date == date)
        ))
        taken_ids = set(self.session.scalars(
            select(Booking.slot_id)
            .join(Slot, Booking.slot_id == Slot.id)
            .where(
                Booking.client_id == self.client_id,
                Booking.status == BOOKING_CONFIRMED,
                Slot.slot_date == date,
            )
        ))
        by_court_time: dict[tuple[int, dt.time], list[Slot]] = {}
        for s in slots:
            by_court_time.setdefault((s.court_id, s.start_time), []).append(s)

        rows: list[OccupancyRow] = []
        for court in courts:
            cells = [
                OccupancyCell(
                    start_time=t,
                    status=self._occupancy_status(by_court_time.get((court.id, t), []), taken_ids),
                )
                for t in times
            ]
            rows.append(OccupancyRow(court_id=court.id, court_name=court.name, cells=cells))
        return OccupancyGrid(date=date, times=times, rows=rows)

    @staticmethod
    def _occupancy_status(slots_at_time: list[Slot], taken_ids: set[int]) -> str:
        if not slots_at_time:
            return "blocked"  # no slot generated here → outside the operating window
        available = [s for s in slots_at_time if s.status == SLOT_AVAILABLE]
        if not available:
            return "blocked"  # every section here is admin-blocked
        taken = sum(1 for s in available if s.id in taken_ids)
        if taken > 0:
            return "booked"
        if any(s.is_member_only for s in available):
            return "peak"
        return "available"

    def get_dashboard_stats(self) -> DashboardStats:
        """Aggregates for the Overview cards, weekly chart, and Reports page."""
        rows = self.session.execute(
            select(Slot.slot_date, Booking.amount, Booking.source)
            .join(Slot, Booking.slot_id == Slot.id)
            .where(
                Booking.client_id == self.client_id,
                Booking.is_primary.is_(True),
                Booking.status == BOOKING_CONFIRMED,
            )
        ).all()
        today = self.today

        bookings_today = sum(1 for d, _, _ in rows if d == today)
        revenue_today = sum(float(a or 0) for d, a, _ in rows if d == today)
        upcoming = sum(1 for d, _, _ in rows if d >= today)
        total_revenue = sum(float(a or 0) for _, a, _ in rows)
        via_voice = sum(1 for _, _, src in rows if src == "voice")

        # Current calendar week, Mon–Sun, keyed by slot_date.
        week_start = today - dt.timedelta(days=today.weekday())
        labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        series: list[DaySeries] = []
        for i in range(7):
            d = week_start + dt.timedelta(days=i)
            amounts = [float(a or 0) for dd, a, _ in rows if dd == d]
            series.append(DaySeries(date=d, label=labels[i], bookings=len(amounts), revenue=sum(amounts)))

        active_members = sum(
            1 for m in self.session.scalars(select(Member).where(Member.client_id == self.client_id))
            if m.is_active(today)
        )
        court_count = self.session.scalar(
            select(func.count(Court.id)).where(Court.client_id == self.client_id)
        ) or 0

        return DashboardStats(
            today=today,
            bookings_today=bookings_today,
            revenue_today=revenue_today,
            upcoming=upcoming,
            active_members=active_members,
            total_bookings=len(rows),
            total_revenue=total_revenue,
            via_voice=via_voice,
            court_count=int(court_count),
            series=series,
        )

    def list_calls(self, limit: int = 50) -> list[CallSummary]:
        """Most-recent handled calls for the Live Calls page, newest first.

        Populated by the voice agent's call logger when a call ends. Empty until the agent
        has handled at least one call.
        """
        rows = self.session.scalars(
            select(Call)
            .where(Call.client_id == self.client_id)
            .order_by(Call.started_at.desc(), Call.id.desc())
            .limit(limit)
        ).all()
        return [
            CallSummary(
                call_id=c.id,
                caller_name=c.caller_name,
                caller_phone=c.caller_phone,
                started_at=c.started_at,
                duration_seconds=int(c.duration_seconds or 0),
                outcome=c.outcome,
                language=c.language,
                summary=c.summary,
            )
            for c in rows
        ]

    def get_call(self, call_id: int) -> CallDetail:
        """One call with its full transcript. Tenant-scoped like every other read."""
        call = self.session.get(Call, call_id)
        if call is None or call.client_id != self.client_id:
            raise errors.SlotNotFound("No such call.")
        return CallDetail(
            call_id=call.id,
            caller_name=call.caller_name,
            caller_phone=call.caller_phone,
            started_at=call.started_at,
            ended_at=call.ended_at,
            duration_seconds=int(call.duration_seconds or 0),
            outcome=call.outcome,
            language=call.language,
            summary=call.summary,
            turns=[CallTurnInfo(role=t.role, text=t.text, ts=t.ts) for t in call.turns],
        )

    # ---- internals -------------------------------------------------------

    @staticmethod
    def _validate_customer(name: str, phone: str) -> tuple[str, str]:
        """Clean and validate caller-supplied identity; returns (name, normalized_phone).

        The normalized phone is what gets STORED, so member/group matching and
        owner lookups work regardless of the +91/spacing format the caller used.
        """
        name = (name or "").strip()[:200]
        if not name:
            raise errors.InvalidInput("A name is required to book.")
        normalized = normalize_phone(phone or "")
        if not 7 <= len(normalized) <= 15:
            raise errors.InvalidInput("A valid phone number is required to book.")
        return name, normalized

    def _offerings_for_sport(self, sport: str) -> list[Offering]:
        target = sport.strip().lower()
        return list(self.session.scalars(
            select(Offering)
            .join(Sport, Offering.sport_id == Sport.id)
            .where(Offering.client_id == self.client_id, func.lower(Sport.name) == target)
        ))

    def _taken_clause(self):
        """Correlated EXISTS: a confirmed booking references this slot."""
        return (
            select(Booking.id)
            .where(Booking.slot_id == Slot.id, Booking.status == BOOKING_CONFIRMED)
            .exists()
        )

    def _free_section_slots(
        self,
        court_id: int,
        date: dt.date,
        section_kind: str | None,
        time: dt.time | None = None,
        lock: bool = False,
    ) -> list[Slot]:
        """Available, un-taken section-slots on a court for a date, optionally one kind / one time."""
        stmt = (
            select(Slot)
            .join(Section, Slot.section_id == Section.id)
            .where(
                Slot.client_id == self.client_id,
                Section.court_id == court_id,
                Slot.slot_date == date,
                Slot.status == SLOT_AVAILABLE,
                ~self._taken_clause(),
            )
        )
        if section_kind is not None:
            stmt = stmt.where(Section.kind == section_kind)
        if time is not None:
            stmt = stmt.where(Slot.start_time == time)
        if lock:
            stmt = stmt.with_for_update()  # no-op on SQLite; real row lock on Postgres
        return list(self.session.scalars(stmt))

    @staticmethod
    def _allocate(slots: list[Slot], n: int) -> list[Slot]:
        """Pick ``n`` section-slots, preferring middle/standard over rim (keeps rims for hoops)."""
        return sorted(slots, key=lambda s: (s.section.alloc_priority, s.id))[:n]

    def _check_rules_and_price(self, offering, chosen: list[Slot], phone: str,
                               date: dt.date, time: dt.time) -> tuple[bool, float]:
        """Membership / group / weekly-cap checks + pricing for a (re)booking. Raises on violation."""
        is_member = self.verify_member(phone).can_book_member_only
        if any(s.is_member_only for s in chosen) and not is_member:
            raise errors.MembershipRequired("That slot is reserved for active members.")
        group_check = self.check_group_restriction(phone, date, time)
        if not group_check.allowed:
            raise errors.GroupRestrictionViolation(group_check.reason or "Group booking restriction.")
        cap_check = self._check_group_weekly_cap(phone, date)
        if not cap_check.allowed:
            raise errors.GroupRestrictionViolation(cap_check.reason or "Group weekly limit reached.")
        amount = 0.0 if is_member else float(offering.price or 0)
        return is_member, amount

    def _insert_rows(self, offering, chosen: list[Slot], name: str, phone: str,
                     source: str, amount: float) -> None:
        """Add one Booking row per chosen section; the first is primary and carries the price."""
        group_id = uuid.uuid4().hex if len(chosen) > 1 else None
        for i, slot in enumerate(chosen):
            self.session.add(Booking(
                client_id=self.client_id, slot_id=slot.id, court_id=offering.court_id,
                section_id=slot.section_id, sport_id=offering.sport_id, offering_id=offering.id,
                booking_group_id=group_id, is_primary=(i == 0),
                customer_name=name, customer_phone=phone,
                amount=amount if i == 0 else 0, status=BOOKING_CONFIRMED, source=source,
            ))

    def _owned_primary(self, booking_id: int) -> Booking:
        b = self.session.get(Booking, booking_id)
        if b is None or b.client_id != self.client_id or not b.is_primary:
            raise errors.SlotNotFound("No such booking.")
        if b.status != BOOKING_CONFIRMED:
            raise errors.SlotUnavailable("That booking is not active.")
        return b

    def _group_rows(self, primary: Booking) -> list[Booking]:
        """The confirmed rows making up a logical booking (all sections of a group, or just one)."""
        if primary.booking_group_id is None:
            return [primary]
        return list(self.session.scalars(
            select(Booking).where(
                Booking.booking_group_id == primary.booking_group_id,
                Booking.status == BOOKING_CONFIRMED,
            )
        ))

    def _group_section_labels(self, primary: Booking) -> list[str]:
        rows = self._group_rows(primary)
        labels = self.session.scalars(
            select(Section.label).where(Section.id.in_([r.section_id for r in rows]))
        ).all()
        return sorted(labels)

    def _find_member(self, phone: str) -> Member | None:
        target = normalize_phone(phone)
        members = self.session.scalars(
            select(Member).where(Member.client_id == self.client_id)
        ).all()
        for m in members:
            if normalize_phone(m.phone) == target:
                return m
        return None

    def _option_info(self, offering: Offering, chosen: list[Slot]) -> OptionInfo:
        sample = chosen[0]
        return OptionInfo(
            offering_id=offering.id,
            option_name=offering.name,
            court_name=offering.court.name,
            sport=offering.sport.name,
            slot_date=sample.slot_date,
            start_time=sample.start_time,
            end_time=sample.end_time,
            price=float(offering.price or 0),
            member_price=0,
            sections_required=offering.sections_required,
            is_member_only=any(s.is_member_only for s in chosen),
        )

    def _confirmation(
        self, offering: Offering, chosen: list[Slot], primary: Booking, amount: float, is_member: bool
    ) -> BookingConfirmation:
        sample = chosen[0]
        return BookingConfirmation(
            booking_id=primary.id,
            booking_group_id=primary.booking_group_id,
            option_name=offering.name,
            court_name=offering.court.name,
            facility_name=offering.court.facility.name,
            sport=offering.sport.name,
            slot_date=sample.slot_date,
            start_time=sample.start_time,
            end_time=sample.end_time,
            customer_name=primary.customer_name,
            sections=[s.section.label for s in chosen],
            amount=float(amount),
            is_member_booking=is_member,
        )
