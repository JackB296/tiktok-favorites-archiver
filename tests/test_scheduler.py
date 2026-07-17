"""Run schedule validation, DST policy, catch-up, and durable occurrence state."""
from datetime import datetime, timezone
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core import scheduler, store


def base(**changes):
    return {
        "name": "Nightly", "run_kind": "sync", "cadence": "daily",
        "local_time": "02:30", "weekday": None,
        "timezone": "America/New_York", "enabled": True, **changes,
    }


def test_validation_and_next_due_are_explicit():
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    prepared = scheduler.prepare(base(), now)
    assert prepared["next_due_at"].startswith("2026-01-02T07:30")
    for bad in (
        base(local_time="25:00"), base(timezone="Nope/Nowhere"),
        base(cadence="weekly", weekday=9),
    ):
        try:
            scheduler.prepare(bad, now)
            raise AssertionError("expected validation error")
        except ValueError:
            pass


def test_dst_gap_advances_and_repeat_runs_once_per_local_date():
    gap = scheduler._occurrence_on(base(), datetime(2026, 3, 8).date())
    assert gap.isoformat().startswith("2026-03-08T07:00")
    repeated = base(local_time="01:30")
    first = scheduler._occurrence_on(repeated, datetime(2026, 11, 1).date())
    assert first.isoformat().startswith("2026-11-01T05:30")
    row = {**repeated, "last_local_date": "2026-11-01"}
    assert scheduler.due_occurrence(row, datetime(2026, 11, 1, 7, tzinfo=timezone.utc)) is None


def test_busy_defers_and_startup_catches_up_only_latest_occurrence():
    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "archive.db")
        conn = store.init_db(store.connect(db_path))
        values = scheduler.prepare(
            base(local_time="08:00", timezone="UTC"),
            datetime(2026, 7, 16, 7, tzinfo=timezone.utc),
        )
        schedule = store.save_run_schedule(conn, values)
        conn.execute(
            "UPDATE backfill_state SET status = 'completed', completed_at = updated_at "
            "WHERE name = 'discovery-identities-v1'"
        )
        conn.commit()
        conn.close()

        class Jobs:
            running = True
            starts = []
            def is_running(self): return self.running
            def start(self, kind):
                self.starts.append(kind)
                self.running = True
                return True

        jobs = Jobs()
        clock = lambda: datetime(2026, 7, 17, 9, tzinfo=timezone.utc)
        service = scheduler.Scheduler(db_path, jobs, clock=clock)
        assert service.tick() is False
        jobs.running = False
        assert service.tick() is True
        assert jobs.starts == ["sync"]
        jobs.running = False
        service.tick()  # records outcome; does not repeat July 17
        conn = store.connect(db_path)
        row = store.get_run_schedule(conn, schedule["id"])
        assert row["last_local_date"] == "2026-07-17"
        conn.close()


if __name__ == "__main__":
    for name, fn in sorted(globals().copy().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
