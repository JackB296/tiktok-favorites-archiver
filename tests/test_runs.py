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


def test_execute_adopts_a_pause_issued_between_begin_and_the_thread_starting():
    """Regression: a pause accepted right after ``begin`` must not be stomped
    by ``execute`` rewriting ``running``. The worker must observe the pause."""
    conn = _db()
    runs.begin(conn, "sync")
    assert store.set_active_run_state(conn, "paused") is True

    seen = []

    def worker(conn, _download_dir, control=None, **_kwargs):
        seen.append(store.get_run_state(conn)["state"])

    runs.execute(conn, "sync", worker, "/tmp/archive")
    assert seen == ["paused"]


def test_execute_adopts_a_stop_issued_between_begin_and_the_thread_starting():
    conn = _db()
    runs.begin(conn, "sync")
    assert store.set_active_run_state(conn, "stopping") is True

    def worker(conn, _download_dir, control=None, **_kwargs):
        assert control.should_continue() is False

    runs.execute(conn, "sync", worker, "/tmp/archive")
    assert store.get_run_state(conn)["state"] == "stopped"


def test_execute_owns_the_run_history_row():
    conn = _db()

    runs.execute(conn, "sync", lambda *_args, **_kwargs: None, "/tmp/archive")
    history = store.list_run_history(conn)
    assert len(history) == 1
    assert history[0]["kind"] == "sync"
    assert history[0]["outcome"] == "completed"
    assert history[0]["finished_at"] is not None


def test_execute_history_outcome_matches_a_stop_and_a_failure():
    conn = _db()

    def stopping_worker(conn, *_args, **_kwargs):
        store.set_active_run_state(conn, "stopping")

    runs.execute(conn, "sync", stopping_worker, "/tmp/archive")
    try:
        runs.execute(conn, "sync", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("x")), "/tmp/archive")
    except RuntimeError:
        pass
    outcomes = [row["outcome"] for row in store.list_run_history(conn)]
    assert outcomes == ["failed", "stopped"]  # newest first


def test_control_should_continue_blocks_while_paused_then_reports_stop():
    conn = _db()
    store.set_run_state(conn, state="paused")
    waits = {"count": 0}

    def wait():
        waits["count"] += 1
        store.set_run_state(conn, state="stopping")

    control = runs.RunControl(conn, wait=wait)
    assert control.should_continue() is False
    assert waits["count"] == 1
    assert control.stop_requested() is True


def test_recover_heals_a_crash_stale_active_state():
    """Regression: execute adopts active states (for the begin->thread window),
    so a crash-stale 'paused' left in the DB would block the next run forever
    unless recover() resets it at process start."""
    for stale in ("running", "paused", "stopping"):
        conn = _db()
        store.set_run_state(conn, state=stale, phase="sync")
        runs.recover(conn)
        state = store.get_run_state(conn)
        assert (state["state"], state["phase"]) == ("idle", None), stale

        # And the healed run then actually processes work.
        seen = []
        runs.execute(conn, "sync", lambda *a, **k: seen.append(True), "/tmp/archive")
        assert seen == [True]


def test_recover_leaves_terminal_states_alone():
    for terminal in ("idle", "stopped", "failed"):
        conn = _db()
        store.set_run_state(conn, state=terminal, phase=None)
        runs.recover(conn)
        assert store.get_run_state(conn)["state"] == terminal


def test_drive_pool_stops_submitting_once_halted():
    """Pins drive's OWN submission-loop check: a fake control that halts after
    two approvals must cap submissions, regardless of what handle does."""
    class FakeControl:
        def __init__(self):
            self.approvals = 0

        def should_continue(self):
            self.approvals += 1
            return self.approvals <= 2

    handled = []
    runs.drive(list(range(10)), 3, FakeControl(), handled.append)
    assert handled == [0, 1]  # third approval refused -> submissions stop


def test_begin_and_abandon_round_trip():
    conn = _db()
    runs.begin(conn, "sync")
    state = store.get_run_state(conn)
    assert (state["state"], state["phase"]) == ("running", "sync")
    runs.abandon(conn)
    state = store.get_run_state(conn)
    assert (state["state"], state["phase"]) == ("idle", None)


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"PASS {name}")
