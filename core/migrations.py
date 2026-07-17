"""Durable schema-version and resumable-backfill registry."""
from datetime import datetime


CURRENT_SCHEMA_VERSION = 2

REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backfill_state (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed')),
    cursor TEXT,
    processed INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
"""


class MigrationError(RuntimeError):
    """The database cannot be safely opened by this app version."""


def _now():
    return datetime.now().isoformat(timespec="seconds")


def install_registry(conn):
    """Create bookkeeping after all version-1 structural migrations succeed."""
    conn.executescript(REGISTRY_SCHEMA)
    row = conn.execute(
        "SELECT version FROM schema_metadata WHERE id = 1"
    ).fetchone()
    if row is not None and row["version"] > CURRENT_SCHEMA_VERSION:
        raise MigrationError(
            f"database schema {row['version']} is newer than supported "
            f"schema {CURRENT_SCHEMA_VERSION}"
        )
    if row is None:
        conn.execute(
            "INSERT INTO schema_metadata (id, version, updated_at) VALUES (1, ?, ?)",
            (CURRENT_SCHEMA_VERSION, _now()),
        )
    elif row["version"] < CURRENT_SCHEMA_VERSION:
        conn.execute(
            "UPDATE schema_metadata SET version = ?, updated_at = ? WHERE id = 1",
            (CURRENT_SCHEMA_VERSION, _now()),
        )


def schema_version(conn):
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_metadata'"
    ).fetchone()
    if exists is None:
        return 0
    row = conn.execute(
        "SELECT version FROM schema_metadata WHERE id = 1"
    ).fetchone()
    return int(row["version"]) if row is not None else 0


def ensure_backfill(conn, name, total=0):
    now = _now()
    conn.execute(
        "INSERT INTO backfill_state "
        "(name, status, cursor, processed, total, error, created_at, updated_at) "
        "VALUES (?, 'pending', NULL, 0, ?, NULL, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET "
        "total = MAX(backfill_state.total, excluded.total)",
        (name, max(0, int(total)), now, now),
    )
    conn.commit()
    return get_backfill(conn, name)


def get_backfill(conn, name):
    return conn.execute(
        "SELECT * FROM backfill_state WHERE name = ?", (name,)
    ).fetchone()


def list_backfills(conn):
    return conn.execute(
        "SELECT * FROM backfill_state ORDER BY name"
    ).fetchall()


def start_backfill(conn, name):
    cursor = conn.execute(
        "UPDATE backfill_state SET status = 'running', error = NULL, "
        "completed_at = NULL, updated_at = ? "
        "WHERE name = ? AND status != 'completed'",
        (_now(), name),
    )
    conn.commit()
    if cursor.rowcount == 0 and get_backfill(conn, name) is None:
        raise KeyError(name)


def update_backfill(conn, name, *, cursor, processed, total=None):
    processed = max(0, int(processed))
    if total is None:
        result = conn.execute(
            "UPDATE backfill_state SET cursor = ?, processed = ?, updated_at = ? "
            "WHERE name = ? AND status = 'running'",
            (str(cursor), processed, _now(), name),
        )
    else:
        result = conn.execute(
            "UPDATE backfill_state SET cursor = ?, processed = ?, total = ?, updated_at = ? "
            "WHERE name = ? AND status = 'running'",
            (str(cursor), processed, max(processed, int(total)), _now(), name),
        )
    conn.commit()
    if result.rowcount != 1:
        raise MigrationError(f"backfill {name!r} is not running")


def fail_backfill(conn, name, error):
    result = conn.execute(
        "UPDATE backfill_state SET status = 'pending', error = ?, updated_at = ? "
        "WHERE name = ? AND status = 'running'",
        (str(error)[:2000], _now(), name),
    )
    conn.commit()
    if result.rowcount != 1:
        raise MigrationError(f"backfill {name!r} is not running")


def complete_backfill(conn, name):
    now = _now()
    result = conn.execute(
        "UPDATE backfill_state SET status = 'completed', cursor = NULL, "
        "processed = total, error = NULL, completed_at = ?, updated_at = ? "
        "WHERE name = ? AND status = 'running'",
        (now, now, name),
    )
    conn.commit()
    if result.rowcount != 1:
        raise MigrationError(f"backfill {name!r} is not running")
