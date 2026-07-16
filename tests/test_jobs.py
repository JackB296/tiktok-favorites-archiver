"""Tests for server.jobs — Broadcaster fan-out + JobManager control (stdlib).

Uses a temp DB file and injected fake runners, so no requests/moviepy/fastapi.
"""
import os
import sys
import queue
import threading
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store
from server import jobs


def test_broadcaster_fans_out_and_unsubscribes():
    b = jobs.Broadcaster()
    q1, q2 = b.subscribe(), b.subscribe()
    b.publish({"x": 1})
    assert q1.get_nowait() == {"x": 1}
    assert q2.get_nowait() == {"x": 1}
    b.unsubscribe(q1)
    b.publish({"x": 2})
    assert q2.get_nowait() == {"x": 2}
    assert q1.empty()


def _drain_until_complete(q, timeout=3.0):
    events = []
    while True:
        try:
            ev = q.get(timeout=timeout)
        except queue.Empty:
            break
        events.append(ev)
        if ev.get("event") == "complete":
            break
    return events


def test_start_guard_and_progress_and_completion():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()

        release = threading.Event()
        started = threading.Event()

        def fake_runner(conn, download_dir, control=None):
            started.set()
            control.progress({"id": 1, "status": "done"})
            release.wait(3)  # hold the job "running" until released

        jm = jobs.JobManager(dbp, d, runners={"sync": fake_runner})
        q = jm.subscribe()

        assert jm.start("sync") is True
        assert started.wait(3)
        assert jm.is_running() is True
        assert jm.start("sync") is False       # single-job guard
        release.set()

        events = _drain_until_complete(q)
        assert any(e.get("status") == "done" for e in events)
        assert events[-1].get("event") == "complete"


def _run_state(dbp):
    c = store.connect(dbp)
    try:
        return store.get_run_state(c)["state"]
    finally:
        c.close()


def test_controls_refuse_while_idle_and_leave_state_untouched():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        jm = jobs.JobManager(dbp, d, runners={"sync": lambda *a, **k: None})

        assert jm.pause() is False
        assert _run_state(dbp) == "idle"
        assert jm.resume() is False
        assert _run_state(dbp) == "idle"
        assert jm.stop() is False
        assert _run_state(dbp) == "idle"


def test_controls_refuse_after_database_state_finishes_even_if_thread_is_still_alive():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        jm = jobs.JobManager(dbp, d, runners={"sync": lambda *a, **k: None})

        class FinishingThread:
            def is_alive(self):
                return True

        jm._thread = FinishingThread()
        assert jm.pause() is False
        assert _run_state(dbp) == "idle"


def test_controls_set_run_state_while_a_job_is_running():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()

        release = threading.Event()
        started = threading.Event()

        def fake_runner(conn, download_dir, control=None):
            started.set()
            release.wait(3)  # hold the job "running" until released

        jm = jobs.JobManager(dbp, d, runners={"sync": fake_runner})
        q = jm.subscribe()
        assert jm.start("sync") is True
        assert started.wait(3)

        assert jm.pause() is True
        assert _run_state(dbp) == "paused"
        assert jm.resume() is True
        assert _run_state(dbp) == "running"
        assert jm.stop() is True
        assert _run_state(dbp) == "stopping"

        release.set()
        _drain_until_complete(q)


def test_stop_is_not_cancelled_by_pause_or_continue():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()

        release = threading.Event()
        started = threading.Event()

        def fake_runner(conn, download_dir, control=None):
            started.set()
            release.wait(3)  # hold the job "running" until released

        jm = jobs.JobManager(dbp, d, runners={"sync": fake_runner})
        q = jm.subscribe()
        assert jm.start("sync") is True
        assert started.wait(3)

        assert jm.stop() is True
        assert _run_state(dbp) == "stopping"
        assert jm.pause() is False              # Pause must not cancel the Stop
        assert _run_state(dbp) == "stopping"
        assert jm.resume() is False             # neither must a stale Continue
        assert _run_state(dbp) == "stopping"

        release.set()
        _drain_until_complete(q)


def test_controls_work_immediately_after_start_returns():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()

        release = threading.Event()

        def fake_runner(conn, download_dir, control=None):
            release.wait(3)  # block immediately

        jm = jobs.JobManager(dbp, d, runners={"sync": fake_runner})
        q = jm.subscribe()

        assert jm.start("sync") is True
        assert _run_state(dbp) == "running"     # persisted before start() returns
        assert jm.pause() is True

        release.set()
        _drain_until_complete(q)


def test_manager_startup_heals_items_stranded_downloading_by_a_crash():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        conn = store.init_db(store.connect(dbp))
        store.insert_item(conn, 1, "a")
        store.set_status(conn, 1, "downloading")  # orphaned by a hard kill
        conn.close()

        jobs.JobManager(dbp, d, runners={"sync": lambda *a, **k: None})

        conn = store.connect(dbp)
        try:
            row = store.get_item(conn, 1)
            assert row["status"] == "failed"
            assert "interrupted" in row["error"]
        finally:
            conn.close()


def test_manager_startup_heals_a_crash_stale_run_state():
    """A run_state left 'paused' by a hard kill must not survive a restart —
    execute's adopt-active-state logic would otherwise block the next run."""
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        conn = store.init_db(store.connect(dbp))
        store.set_run_state(conn, state="paused", phase="sync")
        conn.close()

        jobs.JobManager(dbp, d, runners={"sync": lambda *a, **k: None})

        assert _run_state(dbp) == "idle"


def test_failure_before_execute_bookkeeping_does_not_strand_running():
    """The scenario the heal write actually targets: start_run_history raising
    between begin() and the worker. The state must end failed, not running."""
    from core import runs as runs_module

    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        jm = jobs.JobManager(dbp, d, runners={"sync": lambda *a, **k: None})
        q = jm.subscribe()

        original = store.start_run_history
        store.start_run_history = lambda conn, kind: (_ for _ in ()).throw(RuntimeError("db locked"))
        try:
            assert jm.start("sync") is True
            events = _drain_until_complete(q)
        finally:
            store.start_run_history = original

        assert events[0]["event"] == "error"
        assert _run_state(dbp) == "failed"          # not a stranded "running"


def test_heal_write_never_clobbers_a_terminal_state():
    """If execute persisted idle and only its LAST bookkeeping raised, the
    jobs-thread heal must not rewrite the legitimate idle to failed."""
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        jm = jobs.JobManager(dbp, d, runners={"sync": lambda *a, **k: None})
        q = jm.subscribe()

        original = store.finish_run_history

        def failing_finish(conn, run_id, outcome, counts):
            raise RuntimeError("disk full at the last write")

        store.finish_run_history = failing_finish
        try:
            assert jm.start("sync") is True
            events = _drain_until_complete(q)
        finally:
            store.finish_run_history = original

        assert events[0]["event"] == "error"
        assert _run_state(dbp) == "idle"            # terminal state preserved


def test_start_fails_fast_while_exclusive_maintenance_holds_the_lock():
    """A long import under run_when_idle must not make Start hang — it now
    returns started=false immediately on lock contention."""
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        jm = jobs.JobManager(dbp, d, runners={"sync": lambda *a, **k: None})

        entered = threading.Event()
        release = threading.Event()

        def slow_maintenance():
            entered.set()
            release.wait(3)
            return "done"

        worker = threading.Thread(target=lambda: jm.run_when_idle(slow_maintenance))
        worker.start()
        assert entered.wait(3)
        try:
            assert jm.start("sync") is False        # fast refusal, no hang
        finally:
            release.set()
            worker.join(3)
        assert jm.start("sync") is True             # and works once free


def test_unknown_runner_returns_false():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        jm = jobs.JobManager(dbp, d, runners={"sync": lambda *a, **k: None})
        assert jm.start("nope") is False


def test_run_when_idle_is_serialized_with_background_job_start():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        release = threading.Event()
        started = threading.Event()

        def fake_runner(*_args, **_kwargs):
            started.set()
            release.wait(3)

        jm = jobs.JobManager(dbp, d, runners={"sync": fake_runner})
        assert jm.run_when_idle(lambda: "migration result") == "migration result"

        assert jm.start("sync") is True
        assert started.wait(3)
        try:
            jm.run_when_idle(lambda: "must not run")
        except jobs.JobBusyError:
            pass
        else:
            raise AssertionError("expected exclusive work to refuse an active job")
        release.set()


def _seed_followup_work(dbp, song_id_enabled):
    """One finished favorite that still needs enrichment and identification."""
    conn = store.connect(dbp)
    try:
        store.insert_item(conn, 1, "https://x/1", status="done")  # caption None, song None
        store.set_library_settings(conn, song_id_enabled=song_id_enabled)
    finally:
        conn.close()


def _recording_runners(calls, kinds=("sync", "enrich", "identify")):
    def make(kind):
        def runner(conn, download_dir, control=None):
            calls.append(kind)
        return runner
    return {kind: make(kind) for kind in kinds}


def _run_history_kinds(dbp):
    conn = store.connect(dbp)
    try:
        return [entry["kind"] for entry in store.list_run_history(conn, 10)]
    finally:
        conn.close()


def test_sync_chains_enrichment_and_identification_when_opted_in():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        _seed_followup_work(dbp, song_id_enabled=True)

        calls = []
        jm = jobs.JobManager(dbp, d, runners=_recording_runners(calls))
        q = jm.subscribe()
        assert jm.start("sync") is True
        _drain_until_complete(q)

        assert calls == ["sync", "enrich", "identify"]
        assert _run_history_kinds(dbp) == ["identify", "enrich", "sync"]
        assert _run_state(dbp) == "idle"


def test_sync_chain_skips_identification_without_the_opt_in():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        _seed_followup_work(dbp, song_id_enabled=False)

        calls = []
        jm = jobs.JobManager(dbp, d, runners=_recording_runners(calls))
        q = jm.subscribe()
        assert jm.start("sync") is True
        _drain_until_complete(q)

        assert calls == ["sync", "enrich"]


def test_sync_chain_skips_followups_with_nothing_to_do():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        # No items at all: enrich and identify have no work; only sync runs.
        conn = store.connect(dbp)
        store.set_library_settings(conn, song_id_enabled=True)
        conn.close()

        calls = []
        jm = jobs.JobManager(dbp, d, runners=_recording_runners(calls))
        q = jm.subscribe()
        assert jm.start("sync") is True
        _drain_until_complete(q)

        assert calls == ["sync"]


def test_stop_during_sync_halts_the_chain():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        _seed_followup_work(dbp, song_id_enabled=True)

        calls = []
        runners = _recording_runners(calls)

        def stopping_sync(conn, download_dir, control=None):
            calls.append("sync")
            store.set_active_run_state(conn, "stopping")  # the user pressed Stop

        runners["sync"] = stopping_sync
        jm = jobs.JobManager(dbp, d, runners=runners)
        q = jm.subscribe()
        assert jm.start("sync") is True
        _drain_until_complete(q)

        assert calls == ["sync"]
        assert _run_state(dbp) == "stopped"


def test_explicitly_started_followup_still_runs_alone():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        # No eligible work, but a direct start must still run its own stage.
        calls = []
        jm = jobs.JobManager(dbp, d, runners=_recording_runners(calls))
        q = jm.subscribe()
        assert jm.start("enrich") is True
        _drain_until_complete(q)
        assert calls == ["enrich"]


def test_runner_failure_is_persisted_and_broadcast():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()

        def failing_runner(*_args, **_kwargs):
            raise RuntimeError("resolver crashed")

        jm = jobs.JobManager(dbp, d, runners={"sync": failing_runner})
        q = jm.subscribe()
        assert jm.start("sync") is True

        events = _drain_until_complete(q)
        assert events[0] == {"event": "error", "error": "resolver crashed"}
        assert events[-1] == {"event": "complete"}
        assert jm.status()["state"] == "failed"
        assert jm.status()["phase"] == "sync"


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failures += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failures else 0)
