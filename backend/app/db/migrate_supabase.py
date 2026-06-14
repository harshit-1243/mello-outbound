"""One-shot Supabase migration: create every table, then enable Row-Level Security.

Usage:
    1. Put your Supabase Postgres URI in backend/.env as DATABASE_URL=...
       (Supabase dashboard → Project Settings → Database → Connection string → URI.)
    2. cd backend && .venv/Scripts/python.exe -m app.db.migrate_supabase
    3. Seed demo data into Supabase:  .venv/Scripts/python.exe -m app.seed

Refuses to run against SQLite — this is the Postgres-only production step. The RLS step is also
idempotent-friendly: if policies already exist it errors clearly, and you can instead paste
migrations/001_enable_rls.sql into the Supabase SQL editor.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Windows consoles default to cp1252, which can't encode the check marks below.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.config import settings
from app.db.base import make_engine
from app.db.init_db import create_all

RLS_SQL = Path(__file__).parent / "migrations" / "001_enable_rls.sql"


def main() -> None:
    url = settings.database_url
    if url.startswith("sqlite"):
        raise SystemExit(
            "DATABASE_URL is SQLite (or blank). Set it to your Supabase Postgres URI in .env first."
        )

    engine = make_engine(url)
    safe = url.split("@")[-1]  # host:port/db, without credentials
    print(f"Connecting to {safe} ...")

    create_all(engine)
    print("✓ Tables created (or already present).")

    sql = RLS_SQL.read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(sql)  # psycopg3 runs a multi-statement script when there are no parameters
        raw.commit()
        print("✓ Row-Level Security enabled on all 11 tables.")
    except Exception as exc:  # noqa: BLE001
        raw.rollback()
        print(f"! RLS step failed: {type(exc).__name__}: {str(exc)[:200]}")
        print("  Fallback: paste app/db/migrations/001_enable_rls.sql into the Supabase SQL editor.")
    finally:
        raw.close()

    print("\nNext:  .venv/Scripts/python.exe -m app.seed   # seed the demo facility into Supabase")


if __name__ == "__main__":
    main()
