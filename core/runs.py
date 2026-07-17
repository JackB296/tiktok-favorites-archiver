"""Archive-run lifecycle module.

The single owner of the persisted Archive-run lifecycle: every ``run_state``
write, the pause/stop polling loop, the bounded worker pool, and run history
live here. Workers implement only Sync / Asset backfill / maintenance policy;
they receive a ``RunControl`` and never touch ``run_state`` themselves.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from core import store


# run_state values that mean "stop pulling new work".
_HALT = ("stopping", "stopped")
# Control states an already-begun run may be in when ``execute`` takes over.
_ACTIVE = ("running", "paused", "stopping")


class RunControl:
    """Pause/stop cooperation handle passed to Archive-run workers.

    ``should_continue()`` blocks while the run is paused and returns False once
    a stop is requested — call it between units of work. ``stop_requested()``
    is the non-blocking variant for phase decisions that must not wait out a
    pause. ``db_lock`` serializes shared-connection access for workers that run
    a thread pool over one SQLite connection.
    """

    def __init__(self, conn, progress=None, wait=None):
        self._conn = conn
        self._progress = progress
        self._run_id = None
        self._kind = None
        self._wait = wait if wait is not None else (lambda: time.sleep(0.1))
        self.db_lock = threading.Lock()

    def bind(self, run_id, kind):
        self._run_id = run_id
        self._kind = kind

    def state(self):
        with self.db_lock:
            return store.get_run_state(self._conn)["state"]

    def should_continue(self):
        """Block while paused; True to keep working, False once stopped."""
        while self.state() == "paused":
            self._wait()
        return self.state() not in _HALT

    def stop_requested(self):
        return self.state() in _HALT

    def progress(self, event):
        if self._progress:
            normalized = dict(event)
            if "kind" in normalized:
                normalized["item_kind"] = normalized.pop("kind")
            normalized = {
                "run_id": self._run_id,
                "kind": self._kind,
                "phase": self._kind,
                "completed": normalized.get("completed"),
                "total": normalized.get("total"),
                **normalized,
            }
            self._progress(normalized)

    def set_phase(self, phase):
        """Update only the phase: writing ``state`` here would overwrite a
        pause or stop issued concurrently."""
        with self.db_lock:
            store.set_run_state(self._conn, phase=phase)


def begin(conn, kind):
    """Persist ``running`` before a run thread starts.

    Called by the job manager so controls issued immediately after Start are
    accepted while the thread spins up; ``execute`` adopts this row instead of
    rewriting it.
    """
    store.set_run_state(conn, state="running", phase=kind)


def abandon(conn):
    """Roll back ``begin`` after a failed thread spawn."""
    store.set_run_state(conn, state="idle", phase=None)


def recover(conn):
    """Heal a run_state stranded by a crash.

    At process start no run can be live, so any persisted active control state
    is stale. Without this, ``execute``'s adopt-active-state logic (which
    exists for the legitimate ``begin``-to-thread-start window) would adopt a
    crash-stale ``paused`` and block forever, or a stale ``stopping`` and do
    nothing. The control-row parallel of ``store.reset_interrupted_downloads``.
    """
    if store.get_run_state(conn)["state"] in _ACTIVE:
        store.set_run_state(conn, state="idle", phase=None)


def drive(items, concurrency, control, handle):
    """Run ``handle(item)`` over ``items`` with a bounded pool, honoring pause/stop.

    ``handle(item)`` does the per-item work and its own DB writes (serialized
    with ``control.db_lock``). Shared by the Sync and Asset backfill
    orchestrators so the pool + pause/stop logic lives in one place.
    """
    if concurrency <= 1:
        for item in items:
            if not control.should_continue():
                break
            handle(item)
        return
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = []
        for item in items:
            if not control.should_continue():
                break
            futures.append(pool.submit(handle, item))
        for f in futures:
            f.result()


def execute(
    conn,
    kind,
    worker,
    download_dir,
    progress=None,
    wait=None,
    pipeline_id=None,
    parent_kind=None,
    phase_index=0,
    retry_of=None,
    **kwargs,
):
    """Run one worker under a ``RunControl``; persist state and run history.

    Adopts an active control state written by ``begin`` rather than rewriting
    it, so a pause/stop issued between ``begin`` and the worker thread starting
    is preserved. Terminal outcome (idle / stopped / failed) and the matching
    run-history row are derived exactly once, here.
    """
    control = RunControl(conn, progress=progress, wait=wait)
    if store.get_run_state(conn)["state"] in _ACTIVE:
        store.set_run_state(conn, phase=kind)  # adopt; preserve the control state
    else:
        store.set_run_state(conn, state="running", phase=kind)
    history_id = store.start_run_history(
        conn, kind, retry_of=retry_of, params=kwargs,
    )
    store.set_run_history_context(
        conn,
        history_id,
        pipeline_id,
        parent_kind or kind,
        kind,
        phase_index,
    )
    control.bind(history_id, kind)
    try:
        result = worker(conn, download_dir, control=control, **kwargs)
    except Exception as error:
        store.set_run_state(conn, state="failed", phase=kind)
        store.finish_run_history(
            conn, history_id, "failed", store.counts_by_status(conn),
            error=str(error),
        )
        raise

    final = "stopped" if store.get_run_state(conn)["state"] in _HALT else "idle"
    store.set_run_state(conn, state=final, phase=None)
    store.finish_run_history(
        conn, history_id,
        "stopped" if final == "stopped" else "completed",
        store.counts_by_status(conn),
    )
    return result
