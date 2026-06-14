"""SQLAlchemy engine / session setup.

Works identically against SQLite (local dev + tests) and Postgres (Supabase) — the only
difference is the connection string. SQLite foreign-key enforcement is enabled explicitly
(it is off by default) so the integrity guarantees match Postgres.
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _enable_sqlite_fk(dbapi_connection, _connection_record):
    """Turn on foreign-key enforcement for SQLite connections."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _normalize_url(url: str) -> str:
    """Map a plain Postgres URL onto the installed psycopg (v3) driver.

    Supabase hands out ``postgresql://...`` (or sometimes ``postgres://...``); SQLAlchemy would
    default that to psycopg2, which we don't install. Rewrite the scheme to ``postgresql+psycopg``
    so a pasted connection string works unchanged.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def make_engine(url: str | None = None) -> Engine:
    url = _normalize_url(url or settings.database_url)
    if url.startswith("sqlite"):
        # check_same_thread=False lets the threaded concurrency test share a file DB.
        engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
        event.listen(engine, "connect", _enable_sqlite_fk)
        return engine
    # Postgres (Supabase): the pooler drops idle connections, so validate each one as it
    # leaves the pool (pre_ping) and recycle before the pooler's idle cutoff. Without this,
    # the first booking after a quiet period fails on a stale connection mid-call.
    return create_engine(url, pool_pre_ping=True, pool_recycle=300, future=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session():
    """FastAPI dependency: yield a session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
