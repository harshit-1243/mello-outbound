"""Exercise the live REST API (scratch SQLite) — endpoints, error paths, latency, CORS.

Run while uvicorn serves app.main:app on :8000 with DATABASE_URL=sqlite:///./audit_scratch.db.
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import datetime as dt
import statistics
import time

import httpx

BASE = "http://127.0.0.1:8001"
TODAY = dt.date.today()
TOMORROW = (TODAY + dt.timedelta(days=1)).isoformat()

c = httpx.Client(base_url=BASE, timeout=15)


def t(label: str, fn):
    t0 = time.perf_counter()
    r = fn()
    ms = (time.perf_counter() - t0) * 1000
    print(f"  [{label}] {r.status_code} in {ms:.0f}ms")
    return r, ms


def main() -> None:
    print("1. health + latency baseline (20 list calls — what the dashboard polls)")
    r, _ = t("health", lambda: c.get("/health"))
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        c.get("/clients/1/bookings")
        times.append((time.perf_counter() - t0) * 1000)
    print(f"  list_bookings p50={statistics.median(times):.0f}ms p95={sorted(times)[18]:.0f}ms")

    print("\n2. availability")
    r, _ = t("avail football tomorrow", lambda: c.get(
        f"/clients/1/availability", params={"sport": "Football", "date": TOMORROW}))
    options = r.json()
    print(f"     {len(options)} options; first: {options[0]['option_name']} "
          f"{options[0]['start_time']} ₹{options[0]['price']}" if options else "     none")
    r, _ = t("avail full day ALL sports payload", lambda: c.get(
        f"/clients/1/availability", params={"sport": "Badminton", "date": TOMORROW}))
    print(f"     badminton payload: {len(r.content)} bytes, {len(r.json())} options")

    print("\n3. booking lifecycle")
    open_opt = next(o for o in options if not o["is_member_only"])
    body = {"name": "Audit Tester", "phone": "9876512345",
            "offering_id": open_opt["offering_id"], "date": TOMORROW,
            "time": open_opt["start_time"][:5]}
    r, _ = t("create", lambda: c.post("/clients/1/bookings", json=body))
    booking = r.json()
    print(f"     booked id={booking['booking_id']} amount={booking['amount']}")

    r, _ = t("double-book (expect 409)", lambda: c.post("/clients/1/bookings", json=body))
    r, _ = t("member-only as stranger (expect 403)", lambda: c.post("/clients/1/bookings", json={
        **body, "time": "18:00", "name": "Stranger", "phone": "9000099999"}))
    r, _ = t("bad offering (expect 404)", lambda: c.post("/clients/1/bookings", json={
        **body, "offering_id": 9999}))
    r, _ = t("garbage date (expect 422)", lambda: c.post("/clients/1/bookings", json={
        **body, "date": "tomorrow"}))

    print("\n4. dashboard ops")
    r, _ = t("list", lambda: c.get("/clients/1/bookings"))
    rows = r.json()
    print(f"     {len(rows)} rows; statuses={ {row['status'] for row in rows} }")
    bid = booking["booking_id"]
    new_time = "21:00"
    r, _ = t("reschedule", lambda: c.post(f"/clients/1/bookings/{bid}/reschedule",
                                          json={"date": TOMORROW, "time": new_time}))
    new_id = r.json().get("booking_id") if r.status_code == 200 else bid
    print(f"     rescheduled -> new booking_id={new_id} (id changed: {new_id != bid})")
    r, _ = t("cancel", lambda: c.post(f"/clients/1/bookings/{new_id}/cancel"))
    r, _ = t("cancel again (expect 4xx)", lambda: c.post(f"/clients/1/bookings/{new_id}/cancel"))
    r, _ = t("cancel nonexistent (expect 404)", lambda: c.post("/clients/1/bookings/99999/cancel"))

    print("\n5. cross-tenant + auth probes")
    r, _ = t("tenant 2 bookings (no auth!)", lambda: c.get("/clients/2/bookings"))
    print(f"     response: {r.json() if r.status_code == 200 else r.text[:100]}")
    r, _ = t("tenant 1 PII open to world", lambda: c.get("/clients/1/bookings"))
    has_pii = any(row.get("customer_phone") for row in r.json()) if r.status_code == 200 else False
    print(f"     anonymous request sees names+phones: {has_pii}")

    print("\n6. CORS preflight from the deployed dashboard origin (Vercel)")
    r = c.options("/clients/1/bookings", headers={
        "Origin": "https://mello-dashboard.vercel.app",
        "Access-Control-Request-Method": "GET",
    })
    allow = r.headers.get("access-control-allow-origin")
    print(f"  [preflight vercel] {r.status_code} allow-origin={allow!r}  -> "
          f"{'BLOCKED (dashboard cannot reach API in prod)' if allow is None else 'ok'}")
    r = c.options("/clients/1/bookings", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
    })
    print(f"  [preflight localhost] {r.status_code} allow-origin={r.headers.get('access-control-allow-origin')!r}")

    print("\n7. past-date handling over REST")
    yesterday = (TODAY - dt.timedelta(days=1)).isoformat()
    r, _ = t("availability yesterday", lambda: c.get(
        "/clients/1/availability", params={"sport": "Football", "date": yesterday}))
    print(f"     yesterday options offered: {len(r.json())} (should be 0)")


if __name__ == "__main__":
    main()
