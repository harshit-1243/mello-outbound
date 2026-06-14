"""Shared pytest fixtures: an isolated in-memory DB, a session, and a seeded world per test."""
from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from tests.factory import build_world, make_memory_engine


@pytest.fixture
def engine():
    eng = make_memory_engine()
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def session(session_factory):
    s = session_factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def world(session):
    return build_world(session)
