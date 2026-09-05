"""Shared request helpers for feature-specific API routers."""
import json

from fastapi import HTTPException

from core import store
from server.archive_items import ArchiveItems


def open_db(request):
    return store.connect(request.app.state.db_path)


class SharedReadConnection:
    """Hands the app-lifetime read connection to `finally: conn.close()`
    handler bodies without letting them actually close it."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


def open_db_read(request):
    """The shared warm-cache connection for strictly read-only handlers.

    Falls back to a fresh connection when the app was built without one
    (feature-router test apps). Never hand this to code that writes: the
    connection is PRAGMA query_only and shared across request threads.
    """
    shared = getattr(request.app.state, "read_conn", None)
    if shared is None:
        return store.connect(request.app.state.db_path)
    return SharedReadConnection(shared)


def items(request, conn):
    return ArchiveItems(conn, request.app.state.download_dir)


async def json_body(request):
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="request body must be valid JSON")
