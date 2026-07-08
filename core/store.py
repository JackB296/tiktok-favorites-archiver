"""SQLite state store: items (== output file numbers) and run control.

Source of truth for the app; retires ``last_downloaded_link.txt``. ``item.id`` is
the ``<n>`` in ``downloads/<n>.mp4``, so Plex numbering stays stable. Resume is
"query pending/failed items in order", not a bookmark file.

Uses only the standard library (``sqlite3``), so it is testable without any
third-party install.
"""
import os
import sqlite3
from datetime import datetime

# Lifecycle vocabularies — kept as data (not DB-enforced) so they can evolve.
ITEM_STATUSES = ("pending", "resolving", "downloading", "done", "failed", "skipped", "expired")
ITEM_KINDS = ("unknown", "video", "slideshow", "unresolved")
RUN_STATES = ("idle", "running", "paused", "stopping", "stopped")

DEFAULT_CONCURRENCY = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS item (
    id           INTEGER PRIMARY KEY,   -- == <n> in downloads/<n>.mp4
    link         TEXT NOT NULL UNIQUE,
    favorited_at TEXT,
    kind         TEXT NOT NULL DEFAULT 'unknown',
    status       TEXT NOT NULL DEFAULT 'pending',
    has_assets   INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    caption      TEXT,
    author       TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_item_status ON item(status);

CREATE TABLE IF NOT EXISTS run_state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    state       TEXT NOT NULL DEFAULT 'idle',
    phase       TEXT,
    concurrency INTEGER NOT NULL DEFAULT 4,
    cobalt_url  TEXT,
    updated_at  TEXT NOT NULL
);
"""


def _now():
    return datetime.now().isoformat(timespec="seconds")


def connect(path=":memory:"):
    if path != ":memory:":
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")  # wait, don't error, under concurrent writers
    return conn


def init_db(conn):
    """Create tables (idempotent) and ensure the singleton run_state row exists."""
    conn.executescript(SCHEMA)
    if conn.execute("SELECT 1 FROM run_state WHERE id = 1").fetchone() is None:
        conn.execute(
            "INSERT INTO run_state (id, state, phase, concurrency, cobalt_url, updated_at) "
            "VALUES (1, 'idle', NULL, ?, NULL, ?)",
            (DEFAULT_CONCURRENCY, _now()),
        )
    conn.commit()
    return conn


# --- items -----------------------------------------------------------------

def get_item(conn, item_id):
    return conn.execute("SELECT * FROM item WHERE id = ?", (item_id,)).fetchone()


def get_item_by_link(conn, link):
    return conn.execute("SELECT * FROM item WHERE link = ?", (link,)).fetchone()


def next_item_id(conn):
    """The next output number: max existing id + 1 (gaps are preserved, like the
    filesystem-based numbering it replaces)."""
    row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM item").fetchone()
    return row["m"] + 1


def insert_item(conn, item_id, link, favorited_at=None, kind="unknown", status="pending"):
    now = _now()
    conn.execute(
        "INSERT INTO item (id, link, favorited_at, kind, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (item_id, link, favorited_at, kind, status, now, now),
    )
    conn.commit()
    return item_id


def upsert_link(conn, link, favorited_at=None):
    """Ensure an item exists for ``link``; return its id.

    Existing links keep their number (idempotent import); new links get the next
    number. If a newly-known ``favorited_at`` arrives for an existing row, fill it.
    """
    existing = get_item_by_link(conn, link)
    if existing is not None:
        if favorited_at and not existing["favorited_at"]:
            conn.execute(
                "UPDATE item SET favorited_at = ?, updated_at = ? WHERE id = ?",
                (favorited_at, _now(), existing["id"]),
            )
            conn.commit()
        return existing["id"]
    return insert_item(conn, next_item_id(conn), link, favorited_at)


def _update(conn, item_id, **fields):
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{col} = ?" for col in fields)
    conn.execute(f"UPDATE item SET {assignments} WHERE id = ?", (*fields.values(), item_id))
    conn.commit()


def set_status(conn, item_id, status, error=None):
    _update(conn, item_id, status=status, error=error)


def set_kind(conn, item_id, kind):
    _update(conn, item_id, kind=kind)


def set_has_assets(conn, item_id, has_assets):
    _update(conn, item_id, has_assets=1 if has_assets else 0)


def set_metadata(conn, item_id, caption, author):
    _update(conn, item_id, caption=caption, author=author)


def items_by_status(conn, statuses):
    placeholders = ",".join("?" for _ in statuses)
    return conn.execute(
        f"SELECT * FROM item WHERE status IN ({placeholders}) ORDER BY id",
        tuple(statuses),
    ).fetchall()


def all_items(conn):
    return conn.execute("SELECT * FROM item ORDER BY id").fetchall()


def counts_by_status(conn):
    rows = conn.execute("SELECT status, COUNT(*) AS c FROM item GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}


# --- run control -----------------------------------------------------------

def get_run_state(conn):
    return conn.execute("SELECT * FROM run_state WHERE id = 1").fetchone()


def set_run_state(conn, **fields):
    if not fields:
        return
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{col} = ?" for col in fields)
    conn.execute(f"UPDATE run_state SET {assignments} WHERE id = 1", tuple(fields.values()))
    conn.commit()
