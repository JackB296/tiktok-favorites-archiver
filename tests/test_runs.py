"""Tests for Archive-run lifecycle ownership."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import runs, store


def _db():
    return store.init_db(store.connect(":memory:"))


def test_execute_marks_a_completed_run_idle():
    conn = _db()

    result = runs.execute(conn, "sync", lambda *_args, **_kwargs: {"done": 1}, "/tmp/archive")

    assert result == {"done": 1}
    state = store.get_run_state(conn)
    assert state["state"] == "idle"
    assert state["phase"] is None


def test_execute_preserves_a_user_stop_as_stopped():
    conn = _db()

    def worker(conn, *_args, **_kwargs):
        store.set_run_state(conn, state="stopping")

    runs.execute(conn, "sync", worker, "/tmp/archive")

    assert store.get_run_state(conn)["state"] == "stopped"


def test_execute_records_an_unexpected_failure():
    conn = _db()

    try:
        runs.execute(conn, "backfill", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")), "/tmp/archive")
    except RuntimeError as error:
        assert str(error) == "boom"
    else:
        raise AssertionError("expected the worker error")

    state = store.get_run_state(conn)
    assert state["state"] == "failed"
    assert state["phase"] == "backfill"


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"PASS {name}")
