"""Background job manager + progress broadcaster (stdlib + core only).

Runs the sync/backfill engine in a daemon thread and fans out progress events to
SSE subscribers. Each thread uses its OWN SQLite connection (WAL + busy_timeout
make that safe) rather than sharing one connection object across threads.

The runners are injectable, so the manager's control logic (single-job guard,
pause/continue/stop → run_state, event fan-out) is unit-testable with a fake
runner — no requests/moviepy needed.
"""
import queue
import threading

from core import enrich, runs, sidecars, store, sync


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
        }
        self._thread = None
        self._broadcaster = Broadcaster()
        self._lock = threading.Lock()
        store.init_db(store.connect(db_path)).close()  # once, not per status poll

    def _conn(self):
        return store.connect(self.db_path)

    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self, kind="sync"):
        with self._lock:
            if self.is_running():
                return False
            runner = self.runners.get(kind)
            if runner is None:
                return False

            def run():
                conn = self._conn()
                history_id = store.start_run_history(conn, kind)
                outcome = "completed"
                try:
                    runs.execute(
                        conn,
                        kind,
                        runner,
                        self.download_dir,
                        progress=self._broadcaster.publish,
                    )
                except Exception as e:  # surface, don't crash the thread silently
                    outcome = "failed"
                    self._broadcaster.publish({"event": "error", "error": str(e)})
                finally:
                    if outcome == "completed" and store.get_run_state(conn)["state"] == "stopped":
                        outcome = "stopped"
                    store.finish_run_history(conn, history_id, outcome, store.counts_by_status(conn))
                    self._broadcaster.publish({"event": "complete"})
                    conn.close()

            self._thread = threading.Thread(target=run, name=f"job-{kind}", daemon=True)
            self._thread.start()
            return True

    def _set_state(self, state):
        conn = self._conn()
        try:
            store.set_run_state(conn, state=state)
        finally:
            conn.close()

    def pause(self):
        self._set_state("paused")

    def resume(self):
        self._set_state("running")

    def stop(self):
        self._set_state("stopping")

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
