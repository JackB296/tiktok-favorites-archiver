"""Background job manager + progress broadcaster (stdlib + core only).

Runs the sync/backfill engine in a daemon thread and fans out progress events to
SSE subscribers. Each thread uses its OWN SQLite connection (WAL + busy_timeout
make that safe) rather than sharing one connection object across threads.

The runners are injectable, so the manager's control logic (single-job guard,
pause/continue/stop → run_state, event fan-out) is unit-testable with a fake
runner — no requests/moviepy needed.
"""
import os
import queue
import threading
import uuid

from core import layout, run_catalog, runs, store


class JobBusyError(RuntimeError):
    """Raised when exclusive maintenance is attempted during an active job."""


class Broadcaster:
    """Thread-safe fan-out of events to subscriber queues."""

    def __init__(self):
        self._subscribers = []
        self._lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event):
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put(event)


class JobManager:
    def __init__(self, db_path, download_dir, runners=None):
        self.db_path = db_path
        self.download_dir = download_dir
        self.runners = runners or run_catalog.default_runners()
        self._thread = None
        self._broadcaster = Broadcaster()
        self._lock = threading.Lock()
        conn = store.init_db(store.connect(db_path))  # once, not per status poll
        store.reset_interrupted_downloads(conn)  # heal rows stranded by a crash
        runs.recover(conn)                       # heal a run_state stranded by a crash
        conn.close()
        self._sweep_stranded_uploads()

    def _sweep_stranded_uploads(self):
        """Remove staged uploads stranded by a crash mid-request.

        Nothing else cleans ``.archive/uploads`` (verify's leftover scan covers
        only the downloads root), and no request can be in flight during
        manager construction.
        """
        uploads = layout.uploads_dir(self.download_dir)
        if not os.path.isdir(uploads):
            return
        for name in os.listdir(uploads):
            try:
                os.unlink(os.path.join(uploads, name))
            except OSError:
                pass

    def _conn(self):
        return store.connect(self.db_path)

    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    def _stage_has_work(self, conn, stage):
        """Whether a chained follow-up stage would do anything at all."""
        return run_catalog.has_work(conn, stage)

    def start(self, kind="sync", retry_of=None, **run_kwargs):
        # Non-blocking: while exclusive maintenance (e.g. a long import) holds
        # the lock, a Start is refused fast ({"started": false}) instead of
        # hanging the request until the maintenance finishes.
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self.is_running():
                return False
            try:
                conn = self._conn()
                try:
                    setting = store.get_pipeline_settings(conn, kind) if kind == "sync" else None
                    stages = run_catalog.pipeline_for(
                        kind, setting["phases"] if setting else None,
                    )
                finally:
                    conn.close()
            except ValueError:
                return False
            if self.runners.get(stages[0]) is None:
                return False
            pipeline_id = uuid.uuid4().hex

            def run():
                # runs.execute owns run_state and the run-history row per
                # stage; this thread sequences the pipeline and surfaces
                # errors and completion to subscribers.
                conn = self._conn()
                try:
                    for position, stage in enumerate(stages):
                        runner = self.runners.get(stage)
                        # The stage the user asked for always runs; follow-ups
                        # are best-effort and skipped when they have no work.
                        if runner is None or (position > 0 and not self._stage_has_work(conn, stage)):
                            continue
                        runs.execute(
                            conn,
                            stage,
                            runner,
                            self.download_dir,
                            progress=self._broadcaster.publish,
                            pipeline_id=pipeline_id,
                            parent_kind=kind,
                            phase_index=position,
                            retry_of=retry_of if position == 0 else None,
                            **run_kwargs,
                        )
                        # A user Stop ends the whole chain, not just the stage.
                        if store.get_run_state(conn)["state"] == "stopped":
                            break
                except Exception as e:  # surface, don't crash the thread silently
                    try:
                        # A failure before execute's own bookkeeping (e.g. the
                        # history insert) must not strand the "running" state
                        # begin() wrote. Guarded transition: only an ACTIVE
                        # state becomes failed — a terminal idle/stopped that
                        # execute already persisted is never clobbered.
                        store.set_active_run_state(conn, "failed")
                    except Exception:
                        pass
                    self._broadcaster.publish({
                        "event": "error", "error": str(e), "run_id": None,
                        "kind": kind, "phase": None, "completed": None, "total": None,
                    })
                finally:
                    conn.close()
                    self._broadcaster.publish({
                        "event": "complete", "run_id": None, "kind": kind,
                        "phase": None, "completed": None, "total": None,
                    })

            # Persist "running" before start() returns so controls issued
            # immediately after Start are not rejected while the thread spins up.
            conn = self._conn()
            try:
                runs.begin(conn, stages[0])
                self._thread = threading.Thread(target=run, name=f"job-{stages[0]}", daemon=True)
                try:
                    self._thread.start()
                except Exception:
                    # A failed spawn must not leave a phantom "running" row.
                    runs.abandon(conn)
                    raise
            finally:
                conn.close()
            return True
        finally:
            self._lock.release()

    def retry(self, run_id):
        conn = self._conn()
        try:
            original = store.get_run_history(conn, run_id)
        finally:
            conn.close()
        if original is None:
            raise ValueError("run history entry not found")
        if original["outcome"] not in ("failed", "stopped"):
            raise ValueError("only failed or stopped runs can be retried")
        if not run_catalog.get(original["kind"]).resumable:
            raise ValueError("this run is not safely retryable")
        started = self.start(
            original["kind"], retry_of=original["id"], **original["params"],
        )
        return {"started": started, "retry_of": original["id"]}

    def run_when_idle(self, operation):
        """Run short exclusive maintenance without racing a job start.

        Both this method and ``start`` use the same lock. Once the idle check
        passes, no Sync/backfill/index job can start until ``operation`` has
        either completed or raised.
        """
        with self._lock:
            if self.is_running():
                raise JobBusyError("an Archive run is currently active")
            return operation()

    def _set_state(self, state):
        if not self.is_running():
            return False
        conn = self._conn()
        try:
            return store.set_active_run_state(conn, state)
        finally:
            conn.close()

    def pause(self):
        return self._set_state("paused")

    def resume(self):
        return self._set_state("running")

    def stop(self):
        return self._set_state("stopping")

    def status(self):
        conn = self._conn()
        try:
            rs = store.get_run_state(conn)
            return {
                "state": rs["state"],
                "phase": rs["phase"],
                "concurrency": rs["concurrency"],
                "running": self.is_running(),
                "counts": store.counts_by_status(conn),
            }
        finally:
            conn.close()

    def subscribe(self):
        return self._broadcaster.subscribe()

    def unsubscribe(self, q):
        self._broadcaster.unsubscribe(q)
