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

        def fake_runner(conn, download_dir, progress=None):
            started.set()
            progress({"id": 1, "status": "done"})
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


def test_controls_set_run_state():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        jm = jobs.JobManager(dbp, d, runners={"sync": lambda *a, **k: None})

        def state():
            c = store.connect(dbp)
            try:
                return store.get_run_state(c)["state"]
            finally:
                c.close()

        jm.pause()
        assert state() == "paused"
        jm.resume()
        assert state() == "running"
        jm.stop()
        assert state() == "stopping"


def test_unknown_runner_returns_false():
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "a.db")
        store.init_db(store.connect(dbp)).close()
        jm = jobs.JobManager(dbp, d, runners={"sync": lambda *a, **k: None})
        assert jm.start("nope") is False


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
