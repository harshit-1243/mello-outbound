"""Prompt-vs-schema coverage (TEST_PLAN section 7, tool-wiring regression).

Every tool the system prompt tells the model to call MUST be (a) handed to the LLM in that
objective's tool schema and (b) backed by a dispatch handler. This guards the bug where the
non-booking objectives named tools (`mark_renewal`, `log_interest`, `record_feedback`, `decline`)
that were never registered — so the live LLM call could not actually complete them.
"""
from __future__ import annotations

import datetime as dt
import re

import pytest

from app.voice.objective import OBJECTIVES
from app.voice.outbound_pipeline_tools import _DISPATCH, build_outbound_tools_schema
from app.voice.outbound_prompts import build_outbound_system_prompt

# Backtick-quoted names in the prompt that look like our tools (snake_case verbs we dispatch).
_TOOL_TOKEN = re.compile(r"`([a-z_]+)`")


def _tools_named_in_prompt(objective: str) -> set[str]:
    sp = build_outbound_system_prompt(objective, "Smash Arena", dt.date(2030, 7, 2), {"service": "x", "when": "y"})
    return {t for t in _TOOL_TOKEN.findall(sp) if t in _DISPATCH}


@pytest.mark.parametrize("objective", list(OBJECTIVES))
def test_every_prompted_tool_is_registered_and_dispatchable(objective):
    schema_names = {s.name for s in build_outbound_tools_schema(objective).standard_tools}
    prompted = _tools_named_in_prompt(objective)
    assert prompted, f"{objective}: prompt referenced no known tools — extraction broke?"
    missing_from_schema = prompted - schema_names
    missing_from_dispatch = prompted - set(_DISPATCH)
    assert not missing_from_schema, f"{objective}: prompted but not in LLM schema: {missing_from_schema}"
    assert not missing_from_dispatch, f"{objective}: prompted but no dispatch handler: {missing_from_dispatch}"


@pytest.mark.parametrize("objective", list(OBJECTIVES))
def test_schema_tools_all_have_dispatch(objective):
    for s in build_outbound_tools_schema(objective).standard_tools:
        assert s.name in _DISPATCH, f"{objective}: schema tool {s.name} has no dispatch handler"


def test_non_booking_objectives_expose_their_affirmative_tool():
    # The exact regression: renewal/feedback/etc. must now offer their completion tool to the LLM.
    expect = {
        "membership_renewal": "mark_renewal",
        "reactivation": "log_interest",
        "promo_offer": "log_interest",
        "feedback": "record_feedback",
    }
    for objective, tool in expect.items():
        names = {s.name for s in build_outbound_tools_schema(objective).standard_tools}
        assert tool in names, f"{objective} should expose {tool} to the LLM"
