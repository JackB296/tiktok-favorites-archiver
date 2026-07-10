"""Archive-run lifecycle module.

Workers implement Sync or Asset backfill policy. This module owns the persisted
run lifecycle around that work so completion, stops, and unexpected failures
have one authoritative outcome.
"""
from core import store


_HALT = ("stopping", "stopped")


def execute(conn, kind, worker, download_dir, **kwargs):
    """Run one worker and persist its terminal Archive-run state."""
    store.set_run_state(conn, state="running", phase=kind)
    try:
        result = worker(conn, download_dir, **kwargs)
    except Exception:
        store.set_run_state(conn, state="failed", phase=kind)
        raise

    current = store.get_run_state(conn)["state"]
    final = "stopped" if current in _HALT else "idle"
    store.set_run_state(conn, state=final, phase=None)
    return result
