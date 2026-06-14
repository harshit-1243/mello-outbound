"""Tests for the voice tool bridge — the contract between the LLM and the booking engine."""
from __future__ import annotations

import datetime as dt

from app.voice.prompts import build_system_prompt
from app.voice.tools import ANTHROPIC_TOOLS, dispatch


def test_tool_list_matches_the_supported_operations():
    names = {t["name"] for t in ANTHROPIC_TOOLS}
    assert names == {
        "check_availability",
        "verify_member",
        "check_group_restriction",
        "create_booking",
        "get_next_available_slot",
        "find_my_bookings",
        "cancel_my_booking",
        "reschedule_my_booking",
    }


def test_check_availability_returns_options_without_identities(session, world):
    out = dispatch(session, world.client_id, "check_availability",
                   {"sport": "Basketball", "date": world.D.isoformat(), "time": "19:00"})
    assert "options" in out
    assert {o["option_name"] for o in out["options"]} == {"Basketball (3-point)", "Basketball (full court)"}
    first = out["options"][0]
    assert "offering_id" in first and "price" in first
    assert "customer_name" not in first and "name" not in first


def test_verify_member_tool_hides_name(session, world):
    out = dispatch(session, world.client_id, "verify_member", {"phone_number": world.rahul})
    assert out["is_member"] is True and out["can_book_member_only"] is True
    assert "name" not in out and "customer_name" not in out


def test_create_booking_tool_success_then_double(session, world):
    args = {"name": "Voice User", "phone_number": world.stranger,
            "offering_id": world.football_off, "date": world.D.isoformat(), "time": "19:00"}
    out = dispatch(session, world.client_id, "create_booking", args)
    assert out["booked"] is True and out["court_name"] == "Turf" and out["amount"] == 1200

    out2 = dispatch(session, world.client_id, "create_booking", args)
    assert out2["error"] == "slot_unavailable"


def test_full_court_tool_reserves_three_sections(session, world):
    out = dispatch(session, world.client_id, "create_booking",
                   {"name": "Baller", "phone_number": world.stranger,
                    "offering_id": world.bball_full_off, "date": world.D.isoformat(), "time": "19:00"})
    assert out["booked"] is True and len(out["sections"]) == 3 and out["amount"] == 1000


def test_create_booking_tool_member_only(session, world):
    out = dispatch(session, world.client_id, "create_booking",
                   {"name": "NoMember", "phone_number": world.stranger,
                    "offering_id": world.football_off, "date": world.D.isoformat(), "time": "18:00"})
    assert out["error"] == "membership_required"


def test_group_restriction_tool(session, world):
    dispatch(session, world.client_id, "create_booking",
             {"name": "Rahul", "phone_number": world.rahul,
              "offering_id": world.football_off, "date": world.D.isoformat(), "time": "19:00"})
    out = dispatch(session, world.client_id, "check_group_restriction",
                   {"phone_number": world.priya, "date": world.D.isoformat(), "time": "19:00"})
    assert out["allowed"] is False


def test_next_slot_tool(session, world):
    out = dispatch(session, world.client_id, "get_next_available_slot",
                   {"sport": "Badminton", "date": world.D.isoformat()})
    assert out["option"]["start_time"] == "18:00:00"


def test_bad_input_and_unknown_tool(session, world):
    bad = dispatch(session, world.client_id, "check_availability", {"sport": "Football", "date": "not-a-date"})
    assert bad["error"] == "bad_input"
    unknown = dispatch(session, world.client_id, "frobnicate", {})
    assert unknown["error"] == "unknown_tool"


def test_system_prompt_has_client_context():
    prompt = build_system_prompt("Smash Arena", dt.date(2026, 6, 2), caller_phone="+919876500001")
    assert "Smash Arena" in prompt
    assert "2026-06-02" in prompt        # today, for relative-date resolution
    assert "HH:MM" in prompt             # instructs 24-hour times for tool calls
    assert "+919876500001" in prompt     # caller's number to confirm


def test_system_prompt_injects_facility_facts_and_never_promises_whatsapp():
    prompt = build_system_prompt(
        "Smash Arena", dt.date(2026, 6, 2),
        facility={"address": "Sector 17, Vashi", "opening": "06:00", "closing": "23:00"},
    )
    assert "Sector 17, Vashi" in prompt
    assert "06:00" in prompt and "23:00" in prompt
    assert "on its way" not in prompt    # the old false WhatsApp promise is gone


# ---- caller-owned cancel / reschedule tools ----

def _book(session, world, phone="+919888877777", time="19:00", offering=None):
    return dispatch(session, world.client_id, "create_booking",
                    {"name": "Owner", "phone_number": phone,
                     "offering_id": offering or world.football_off,
                     "date": world.D.isoformat(), "time": time})


def test_find_my_bookings_matches_any_phone_format(session, world):
    _book(session, world, phone="+91 98888 77777")
    out = dispatch(session, world.client_id, "find_my_bookings", {"phone_number": "9888877777"})
    assert len(out["bookings"]) == 1
    assert out["bookings"][0]["option_name"] == "Football"


def test_find_my_bookings_never_returns_other_callers(session, world):
    _book(session, world, phone="9888877777")
    out = dispatch(session, world.client_id, "find_my_bookings", {"phone_number": world.stranger})
    assert out["bookings"] == []


def test_cancel_my_booking_frees_the_slot(session, world):
    _book(session, world)
    out = dispatch(session, world.client_id, "cancel_my_booking",
                   {"phone_number": "9888877777", "date": world.D.isoformat()})
    assert out["cancelled"] is True
    # The 19:00 turf slot is free again.
    avail = dispatch(session, world.client_id, "check_availability",
                     {"sport": "Football", "date": world.D.isoformat(), "time": "19:00"})
    assert len(avail["options"]) == 1


def test_cancel_with_wrong_phone_is_refused(session, world):
    _book(session, world)
    out = dispatch(session, world.client_id, "cancel_my_booking",
                   {"phone_number": world.stranger, "date": world.D.isoformat()})
    assert out["error"] == "slot_not_found"


def test_cancel_ambiguous_day_asks_for_time(session, world):
    _book(session, world, time="19:00")
    _book(session, world, time="20:00", offering=world.badminton_off)
    out = dispatch(session, world.client_id, "cancel_my_booking",
                   {"phone_number": "9888877777", "date": world.D.isoformat()})
    assert out["error"] == "invalid_input" and "which time" in out["message"]
    # Disambiguated by time -> works.
    out2 = dispatch(session, world.client_id, "cancel_my_booking",
                    {"phone_number": "9888877777", "date": world.D.isoformat(), "time": "20:00"})
    assert out2["cancelled"] is True


def test_reschedule_my_booking_moves_the_slot(session, world):
    _book(session, world)
    out = dispatch(session, world.client_id, "reschedule_my_booking",
                   {"phone_number": "9888877777", "date": world.D.isoformat(),
                    "new_date": world.D.isoformat(), "new_time": "20:00"})
    assert out["rescheduled"] is True and out["start_time"] == "20:00:00"
    # Old slot freed, new slot taken.
    old = dispatch(session, world.client_id, "check_availability",
                   {"sport": "Football", "date": world.D.isoformat(), "time": "19:00"})
    assert len(old["options"]) == 1
