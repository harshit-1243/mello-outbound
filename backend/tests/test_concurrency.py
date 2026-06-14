"""The race test: many callers hit the same slot at once — exactly one booking may win.

This is the playbook's non-negotiable "no double-booking" guarantee under real contention. Uses a
file-backed SQLite DB so each thread has its own connection; a Barrier maximizes the overlap.
"""
from __future__ import annotations

import datetime as dt
import threading

from sqlalchemy.orm import sessionmaker

from app.booking import errors
from app.booking.service import BookingService
from tests.factory import build_world, make_file_engine

N_CALLERS = 8


def test_concurrent_booking_has_single_winner(tmp_path):
    engine = make_file_engine(str(tmp_path / "race.db"))
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    setup = Session()
    world = build_world(setup)
    setup.close()

    results: list[str] = []
    results_lock = threading.Lock()
    start_barrier = threading.Barrier(N_CALLERS)

    def book(idx: int) -> None:
        start_barrier.wait()  # release all threads simultaneously
        db = Session()
        try:
            svc = BookingService(db, world.client_id)
            svc.create_booking(
                f"Caller {idx}", f"900000{idx:04d}", world.football_off, world.D, dt.time(19, 0)
            )
            outcome = "ok"
        except errors.SlotUnavailable:
            outcome = "unavailable"
        except Exception as exc:  # surfaces unexpected errors (e.g. lock timeouts) in the assert
            outcome = f"error:{type(exc).__name__}"
        finally:
            db.close()
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=book, args=(i,)) for i in range(N_CALLERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    engine.dispose()

    assert results.count("ok") == 1, results
    assert results.count("unavailable") == N_CALLERS - 1, results
