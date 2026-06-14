"""REST surface smoke tests — proves the engine is reachable over HTTP."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.config as config_module
from app.db.base import get_session
from app.main import app
from tests.factory import build_world, make_memory_engine


@pytest.fixture
def api():
    engine = make_memory_engine()
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    setup = Session()
    world = build_world(setup)
    setup.close()

    def _override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = _override
    yield TestClient(app), world
    app.dependency_overrides.clear()
    engine.dispose()


def test_health(api):
    client, _ = api
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_availability_and_double_booking_flow(api):
    client, world = api
    cid = world.client_id

    r = client.get(f"/clients/{cid}/availability",
                   params={"sport": "Football", "date": world.D.isoformat()})
    assert r.status_code == 200 and len(r.json()) == 3  # three time blocks

    payload = {"name": "Test User", "phone": world.stranger,
               "offering_id": world.football_off, "date": world.D.isoformat(), "time": "19:00"}
    r = client.post(f"/clients/{cid}/bookings", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["court_name"] == "Turf" and r.json()["amount"] == 1200

    r2 = client.post(f"/clients/{cid}/bookings", json=payload)
    assert r2.status_code == 409 and r2.json()["code"] == "slot_unavailable"


def test_member_only_booking_returns_403(api):
    client, world = api
    payload = {"name": "Stranger", "phone": world.stranger,
               "offering_id": world.football_off, "date": world.D.isoformat(), "time": "18:00"}
    r = client.post(f"/clients/{world.client_id}/bookings", json=payload)
    assert r.status_code == 403 and r.json()["code"] == "membership_required"


def test_verify_member_and_next_slot_endpoints(api):
    client, world = api
    cid = world.client_id

    r = client.get(f"/clients/{cid}/members/{world.rahul}")
    assert r.status_code == 200 and r.json()["is_member"] is True

    r = client.get(f"/clients/{cid}/next-slot",
                   params={"sport": "Badminton", "date": world.D.isoformat()})
    assert r.status_code == 200 and r.json()["start_time"] == "18:00:00"


def test_list_bookings_rest(api):
    client, world = api
    cid = world.client_id

    # Empty before any bookings.
    r = client.get(f"/clients/{cid}/bookings")
    assert r.status_code == 200 and r.json() == []

    # Create two bookings (football + badminton).
    payload_f = {"name": "Alice", "phone": world.stranger,
                 "offering_id": world.football_off, "date": world.D.isoformat(), "time": "19:00"}
    payload_b = {"name": "Bob", "phone": "9111122222",
                 "offering_id": world.badminton_off, "date": world.D.isoformat(), "time": "19:00"}
    client.post(f"/clients/{cid}/bookings", json=payload_f)
    client.post(f"/clients/{cid}/bookings", json=payload_b)

    r = client.get(f"/clients/{cid}/bookings")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    sports = {row["sport"] for row in data}
    assert sports == {"Football", "Badminton"}


def test_cancel_via_rest(api):
    client, world = api
    cid = world.client_id

    # Book and then cancel.
    payload = {"name": "Canceller", "phone": world.stranger,
               "offering_id": world.football_off, "date": world.D.isoformat(), "time": "19:00"}
    r = client.post(f"/clients/{cid}/bookings", json=payload)
    booking_id = r.json()["booking_id"]

    r = client.post(f"/clients/{cid}/bookings/{booking_id}/cancel")
    assert r.status_code == 200 and r.json()["cancelled"] is True

    # Slot freed — the same time is available again.
    r = client.get(f"/clients/{cid}/availability",
                   params={"sport": "Football", "date": world.D.isoformat(), "time": "19:00"})
    assert r.status_code == 200 and len(r.json()) == 1

    # Cancelling again returns 409 (SlotUnavailable — booking is no longer active/confirmed).
    r = client.post(f"/clients/{cid}/bookings/{booking_id}/cancel")
    assert r.status_code == 409


def test_reschedule_via_rest(api):
    client, world = api
    cid = world.client_id

    payload = {"name": "Mover", "phone": world.stranger,
               "offering_id": world.football_off, "date": world.D.isoformat(), "time": "19:00"}
    r = client.post(f"/clients/{cid}/bookings", json=payload)
    booking_id = r.json()["booking_id"]

    # Move to 20:00 on the same day.
    r = client.post(f"/clients/{cid}/bookings/{booking_id}/reschedule",
                    json={"date": world.D.isoformat(), "time": "20:00"})
    assert r.status_code == 200
    assert r.json()["start_time"] == "20:00:00"

    # Old slot (19:00) is free again.
    r = client.get(f"/clients/{cid}/availability",
                   params={"sport": "Football", "date": world.D.isoformat(), "time": "19:00"})
    assert len(r.json()) == 1

    # New slot (20:00) is taken — a second booking there should fail.
    payload2 = {"name": "Blocker", "phone": "9333300000",
                "offering_id": world.football_off, "date": world.D.isoformat(), "time": "20:00"}
    r = client.post(f"/clients/{cid}/bookings", json=payload2)
    assert r.status_code == 409


def test_group_check_via_rest(api):
    client, world = api
    cid = world.client_id

    # Before any bookings: group check should be allowed.
    r = client.post(f"/clients/{cid}/group-check",
                    json={"phone": world.priya, "date": world.D.isoformat(), "time": "19:00"})
    assert r.status_code == 200 and r.json()["allowed"] is True

    # Rahul (same group) books 19:00 — Priya should now be blocked at that time.
    client.post(f"/clients/{cid}/bookings",
                json={"name": "Rahul", "phone": world.rahul,
                      "offering_id": world.football_off, "date": world.D.isoformat(), "time": "19:00"})

    r = client.post(f"/clients/{cid}/group-check",
                    json={"phone": world.priya, "date": world.D.isoformat(), "time": "19:00"})
    assert r.status_code == 200
    assert r.json()["allowed"] is False
    assert "Sunday League" in r.json()["group_name"]


def test_list_bookings_include_cancelled(api):
    client, world = api
    cid = world.client_id

    payload = {"name": "Ghost", "phone": world.stranger,
               "offering_id": world.football_off, "date": world.D.isoformat(), "time": "19:00"}
    r = client.post(f"/clients/{cid}/bookings", json=payload)
    booking_id = r.json()["booking_id"]
    client.post(f"/clients/{cid}/bookings/{booking_id}/cancel")

    # Default (no cancelled): empty.
    r = client.get(f"/clients/{cid}/bookings")
    assert r.json() == []

    # include_cancelled=true: the cancelled row is present.
    r = client.get(f"/clients/{cid}/bookings", params={"include_cancelled": "true"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1 and rows[0]["status"] == "cancelled"


def test_cross_tenant_cancel_rejected(api):
    client, world = api

    # Tenant A creates a booking.
    payload = {"name": "TenantA User", "phone": world.stranger,
               "offering_id": world.football_off, "date": world.D.isoformat(), "time": "19:00"}
    r = client.post(f"/clients/{world.client_id}/bookings", json=payload)
    booking_id = r.json()["booking_id"]

    # Tenant B tries to cancel Tenant A's booking_id — must be rejected (404).
    r = client.post(f"/clients/{world.client_b_id}/bookings/{booking_id}/cancel")
    assert r.status_code == 404, (
        f"FLAW: Tenant B could cancel Tenant A's booking (got {r.status_code})."
    )

    # Verify the booking is still active under Tenant A.
    r = client.get(f"/clients/{world.client_id}/bookings")
    assert len(r.json()) == 1 and r.json()[0]["status"] == "confirmed"


# ---------------------------------------------------------------------------
# API key authentication
# ---------------------------------------------------------------------------

@pytest.fixture
def secured_api(monkeypatch):
    """api fixture variant with a non-empty API key configured."""
    monkeypatch.setattr(config_module.settings, "api_key", "test-secret-key-abc123")

    engine = make_memory_engine()
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    setup = Session()
    world = build_world(setup)
    setup.close()

    def _override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = _override
    yield TestClient(app), world
    app.dependency_overrides.clear()
    engine.dispose()


def test_health_always_accessible_without_key(secured_api):
    """/health must respond 200 even when api_key is configured and no key is sent."""
    client, _ = secured_api
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_protected_endpoint_requires_key(secured_api):
    """Protected endpoints must return 401 when no API key is provided."""
    client, world = secured_api
    r = client.get(f"/clients/{world.client_id}/availability",
                   params={"sport": "Football", "date": world.D.isoformat()})
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


def test_correct_x_api_key_header_grants_access(secured_api):
    """A correct X-API-Key header must allow the request through."""
    client, world = secured_api
    r = client.get(
        f"/clients/{world.client_id}/availability",
        params={"sport": "Football", "date": world.D.isoformat()},
        headers={"X-API-Key": "test-secret-key-abc123"},
    )
    assert r.status_code == 200


def test_bearer_token_grants_access(secured_api):
    """Authorization: Bearer <key> is an accepted alternative to X-API-Key."""
    client, world = secured_api
    r = client.get(
        f"/clients/{world.client_id}/availability",
        params={"sport": "Football", "date": world.D.isoformat()},
        headers={"Authorization": "Bearer test-secret-key-abc123"},
    )
    assert r.status_code == 200


def test_wrong_api_key_returns_401(secured_api):
    """A wrong key must be rejected with 401, not silently passed through."""
    client, world = secured_api
    r = client.get(
        f"/clients/{world.client_id}/availability",
        params={"sport": "Football", "date": world.D.isoformat()},
        headers={"X-API-Key": "wrong-key"},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Dashboard read endpoints (operator console)
# ---------------------------------------------------------------------------

def test_client_info_endpoint(api):
    client, world = api
    r = client.get(f"/clients/{world.client_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["business_name"] == "Smash Arena"
    assert data["facility_name"] == "Smash Arena, Vashi"
    assert data["court_count"] == 3              # Turf, Basketball Court, Badminton 1
    assert "Football" in data["sports"] and "Badminton" in data["sports"]


def test_list_members_endpoint(api):
    client, world = api
    r = client.get(f"/clients/{world.client_id}/members")
    assert r.status_code == 200
    members = r.json()
    assert len(members) == 3
    by_phone = {m["phone"]: m for m in members}
    assert by_phone["9876500001"]["status"] == "active"     # Rahul
    assert by_phone["9876500003"]["status"] == "expired"    # Amit
    # No bookings yet -> zero visits/spend.
    assert all(m["visits"] == 0 and m["spend"] == 0 for m in members)


def test_list_members_reflects_bookings(api):
    client, world = api
    cid = world.client_id
    # Rahul (active member) books badminton 19:00 — a member books free.
    client.post(f"/clients/{cid}/bookings",
                json={"name": "Rahul", "phone": world.rahul,
                      "offering_id": world.badminton_off, "date": world.D.isoformat(), "time": "19:00"})
    members = {m["phone"]: m for m in client.get(f"/clients/{cid}/members").json()}
    assert members["9876500001"]["visits"] == 1
    assert members["9876500001"]["top_sport"] == "Badminton"
    assert "Sunday League" in members["9876500001"]["group_names"]


def test_occupancy_endpoint(api):
    client, world = api
    cid = world.client_id
    r = client.get(f"/clients/{cid}/occupancy", params={"date": world.D.isoformat()})
    assert r.status_code == 200
    grid = r.json()
    # Hours 18:00–21:00, 2-hour buckets -> columns at 18:00 and 20:00.
    assert grid["times"] == ["18:00:00", "20:00:00"]
    rows = {row["court_name"]: row for row in grid["rows"]}
    assert set(rows) == {"Turf", "Basketball Court", "Badminton 1"}
    # Turf 18:00 is member-only and free -> "peak".
    assert rows["Turf"]["cells"][0]["status"] == "peak"
    # Badminton 18:00 is a normal free slot -> "available".
    assert rows["Badminton 1"]["cells"][0]["status"] == "available"

    # Book badminton 18:00 -> that cell becomes "booked".
    client.post(f"/clients/{cid}/bookings",
                json={"name": "Walk-in", "phone": world.stranger,
                      "offering_id": world.badminton_off, "date": world.D.isoformat(), "time": "18:00"})
    grid2 = client.get(f"/clients/{cid}/occupancy", params={"date": world.D.isoformat()}).json()
    rows2 = {row["court_name"]: row for row in grid2["rows"]}
    assert rows2["Badminton 1"]["cells"][0]["status"] == "booked"


def test_stats_endpoint(api):
    client, world = api
    cid = world.client_id

    before = client.get(f"/clients/{cid}/stats").json()
    assert before["total_bookings"] == 0
    assert before["active_members"] == 2          # Rahul + Priya (Amit expired)
    assert before["court_count"] == 3
    assert len(before["series"]) == 7             # Mon–Sun

    # A paid non-member booking (REST source is "manual", not voice).
    client.post(f"/clients/{cid}/bookings",
                json={"name": "Walk-in", "phone": world.stranger,
                      "offering_id": world.badminton_off, "date": world.D.isoformat(), "time": "19:00"})
    after = client.get(f"/clients/{cid}/stats").json()
    assert after["total_bookings"] == 1
    assert after["upcoming"] == 1                 # world date is in the future
    assert after["total_revenue"] == 500
    assert after["via_voice"] == 0


def test_calls_endpoint_empty_until_voice_line_live(api):
    """The voice line (M3) isn't connected, so the calls endpoint returns an empty list."""
    client, world = api
    r = client.get(f"/clients/{world.client_id}/calls")
    assert r.status_code == 200 and r.json() == []
