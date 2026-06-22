"""Guards on the live /test-call endpoint (TEST_PLAN section 8.2 / 8.3).

The trial dialer may call ONLY an allowlisted number, and only when Twilio is configured. Both
checks run before any real Twilio request, so they're safe to assert without placing a call.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.config as config_module
from app.db.base import get_session
from app.main import app
from tests.factory import build_world, make_memory_engine

ALLOWED = "+918369851507"


@pytest.fixture
def api():
    engine = make_memory_engine()
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    setup = Session()
    build_world(setup)
    setup.close()

    def _override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


# 8.2 — a number not on the allowlist is refused before anything else happens
def test_non_allowlisted_number_is_403(api, monkeypatch):
    monkeypatch.setattr(config_module.settings, "outbound_test_numbers", ALLOWED)
    r = api.post("/clients/1/test-call", json={"to": "+919999999999"})
    assert r.status_code == 403
    assert "allowlist" in r.json()["detail"].lower()


# 8.3 — allowlisted number but Twilio not configured → 400 (no call attempted)
def test_allowlisted_but_twilio_unconfigured_is_400(api, monkeypatch):
    monkeypatch.setattr(config_module.settings, "outbound_test_numbers", ALLOWED)
    monkeypatch.setattr(config_module.settings, "twilio_account_sid", "")
    monkeypatch.setattr(config_module.settings, "twilio_auth_token", "")
    monkeypatch.setattr(config_module.settings, "twilio_from_number", "")
    monkeypatch.setattr(config_module.settings, "public_base_url", "")
    r = api.post("/clients/1/test-call", json={"to": ALLOWED})
    assert r.status_code == 400
    assert "twilio" in r.json()["detail"].lower()
