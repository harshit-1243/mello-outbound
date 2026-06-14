"""Create all tables on the configured engine.

Importing ``app.db.models`` registers every table on ``Base.metadata`` before create_all runs.
Works for both SQLite (dev) and Postgres/Supabase. (On Supabase, run
``migrations/001_enable_rls.sql`` afterwards to turn on Row-Level Security.)
"""
from __future__ import annotations

from sqlalchemy.engine import Engine

from app.db import models  # noqa: F401  — registers tables on Base.metadata
from app.db.base import Base, engine as default_engine


def create_all(engine: Engine | None = None) -> None:
    Base.metadata.create_all(engine or default_engine)


if __name__ == "__main__":
    create_all()
    print("Tables created on", default_engine.url)
