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

from core import enrich, identify, layout, runs, sidecars, store, sync


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
        self.runners = runners or {
            "sync": sync.run_sync,
            "backfill": sync.run_backfill,
            "index": sync.run_index,
            "sidecars": sidecars.run_sidecars,
            "enrich": enrich.run_enrichment,
            "identify": identify.run_identification,
        }
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

    def start(self, kind="sync"):
        # Non-blocking: while exclusive maintenance (e.g. a long import) holds
        # the lock, a Start is refused fast ({"started": false}) instead of
        # hanging the request until the maintenance finishes.
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self.is_running():
                return False
            runner = self.runners.get(kind)
            if runner is None:
                return False

            def run():
                # runs.execute owns run_state and the run-history row; this
                # thread only surfaces errors and completion to subscribers.
                conn = self._conn()
                try:
                    runs.execute(
                        conn,
                        kind,
                        runner,
                        self.download_dir,
                        progress=self._broadcaster.publish,
                    )
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
                    self._broadcaster.publish({"event": "error", "error": str(e)})
                finally:
                    self._broadcaster.publish({"event": "complete"})
                    conn.close()

            # Persist "running" before start() returns so controls issued
            # immediately after Start are not rejected while the thread spins up.
            conn = self._conn()
            try:
                runs.begin(conn, kind)
                self._thread = threading.Thread(target=run, name=f"job-{kind}", daemon=True)
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
