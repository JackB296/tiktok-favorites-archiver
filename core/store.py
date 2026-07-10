"""SQLite state store: items (== output file numbers) and run control.

Source of truth for the app. ``item.id`` is the ``<n>`` in
``downloads/<n>.mp4``, so Plex numbering stays stable. Resume is
"query pending/failed items in order", not a bookmark file.

Uses only the standard library (``sqlite3``), so it is testable without any
third-party install.
"""
import os
import json
import re
import sqlite3
from datetime import datetime

# Lifecycle vocabularies — kept as data (not DB-enforced) so they can evolve.
ITEM_STATUSES = ("pending", "resolving", "downloading", "done", "failed", "skipped", "expired")
ITEM_KINDS = ("unknown", "video", "slideshow", "unresolved")
RUN_STATES = ("idle", "running", "paused", "stopping", "stopped", "failed")

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
    thumbnail_path TEXT,
    duration_s    REAL,
    media_width   INTEGER,
    media_height  INTEGER,
    media_codec   TEXT,
    media_size    INTEGER,
    media_fingerprint TEXT,
    indexed_at    TEXT,
    index_error   TEXT,
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
CREATE TABLE IF NOT EXISTS library_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    index_enabled INTEGER NOT NULL DEFAULT 1,
    thumbnail_width INTEGER NOT NULL DEFAULT 480,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gallery_preset (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    filters_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS item_search USING fts5(
    caption,
    author,
    link,
    content='item',
    content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS item_search_insert AFTER INSERT ON item BEGIN
    INSERT INTO item_search(rowid, caption, author, link) VALUES (new.id, new.caption, new.author, new.link);
END;
CREATE TRIGGER IF NOT EXISTS item_search_delete AFTER DELETE ON item BEGIN
    INSERT INTO item_search(item_search, rowid, caption, author, link) VALUES ('delete', old.id, old.caption, old.author, old.link);
END;
CREATE TRIGGER IF NOT EXISTS item_search_update AFTER UPDATE OF caption, author, link ON item BEGIN
    INSERT INTO item_search(item_search, rowid, caption, author, link) VALUES ('delete', old.id, old.caption, old.author, old.link);
    INSERT INTO item_search(rowid, caption, author, link) VALUES (new.id, new.caption, new.author, new.link);
END;
"""

_ITEM_MIGRATIONS = {
    "thumbnail_path": "TEXT",
    "duration_s": "REAL",
    "media_width": "INTEGER",
    "media_height": "INTEGER",
    "media_codec": "TEXT",
    "media_size": "INTEGER",
    "media_fingerprint": "TEXT",
    "indexed_at": "TEXT",
    "index_error": "TEXT",
}


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
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(item)")}
    for name, type_name in _ITEM_MIGRATIONS.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE item ADD COLUMN {name} {type_name}")
    item_count = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    search_count = conn.execute("SELECT COUNT(*) FROM item_search").fetchone()[0]
    if item_count and search_count != item_count:
        conn.execute("INSERT INTO item_search(item_search) VALUES ('rebuild')")
    if conn.execute("SELECT 1 FROM run_state WHERE id = 1").fetchone() is None:
        conn.execute(
            "INSERT INTO run_state (id, state, phase, concurrency, cobalt_url, updated_at) "
            "VALUES (1, 'idle', NULL, ?, NULL, ?)",
            (DEFAULT_CONCURRENCY, _now()),
        )
    if conn.execute("SELECT 1 FROM library_settings WHERE id = 1").fetchone() is None:
        conn.execute(
            "INSERT INTO library_settings (id, index_enabled, thumbnail_width, updated_at) VALUES (1, 1, 480, ?)",
            (_now(),),
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


def record_work_outcome(conn, item_id, outcome):
    """Persist the lifecycle fields produced by one Sync work attempt.

    The Archive-media implementation reports one outcome; callers do not need
    to coordinate separate status, classification, asset, and error writes.
    """
    fields = {
        "status": outcome["status"],
        "kind": outcome["kind"],
        "error": outcome.get("error"),
    }
    if "has_assets" in outcome:
        fields["has_assets"] = 1 if outcome["has_assets"] else 0
    _update(conn, item_id, **fields)


def record_asset_recovery(conn, item_id, outcome):
    """Persist an Asset backfill classification without changing download state."""
    _update(
        conn,
        item_id,
        kind=outcome["kind"],
        has_assets=1 if outcome["has_assets"] else 0,
    )


def record_media_index(conn, item_id, index, fingerprint):
    """Persist one inspected media record and its reusable thumbnail location."""
    _update(
        conn,
        item_id,
        thumbnail_path=index["thumbnail_path"],
        duration_s=index["duration_s"],
        media_width=index["width"],
        media_height=index["height"],
        media_codec=index["codec"],
        media_size=index["file_size"],
        media_fingerprint=fingerprint,
        indexed_at=_now(),
        index_error=None,
    )


def record_media_index_error(conn, item_id, error):
    """Keep a failed index retryable while retaining the failure reason."""
    _update(conn, item_id, index_error=error)


def items_needing_index(conn):
    """Finished Archive items without a persisted Gallery index."""
    return conn.execute(
        "SELECT * FROM item WHERE status = 'done' AND thumbnail_path IS NULL ORDER BY id"
    ).fetchall()


def items_by_status(conn, statuses):
    placeholders = ",".join("?" for _ in statuses)
    return conn.execute(
        f"SELECT * FROM item WHERE status IN ({placeholders}) ORDER BY id",
        tuple(statuses),
    ).fetchall()


def all_items(conn):
    return conn.execute("SELECT * FROM item ORDER BY id").fetchall()


def _item_filters(query=None, kinds=None, statuses=None):
    clauses = []
    params = []
    if kinds:
        clauses.append("kind IN (%s)" % ",".join("?" for _ in kinds))
        params += list(kinds)
    if statuses:
        clauses.append("status IN (%s)" % ",".join("?" for _ in statuses))
        params += list(statuses)
    return clauses, params


def _fts_query(query):
    """Turn free text into a safe, prefix-searchable FTS expression."""
    terms = re.findall(r"[A-Za-z0-9_]+", query or "")
    return " AND ".join(f'"{term}"*' for term in terms)


def search_items(conn, query=None, kinds=None, statuses=None):
    """Items filtered by a free-text ``query`` and optional classifications."""
    clauses, params = _item_filters(kinds=kinds, statuses=statuses)
    fts_query = _fts_query(query)
    sql = "SELECT item.* FROM item"
    if fts_query:
        sql += " JOIN item_search ON item_search.rowid = item.id"
        clauses.append("item_search MATCH ?")
        params.append(fts_query)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY bm25(item_search), item.id DESC" if fts_query else " ORDER BY item.id"
    return conn.execute(sql, params).fetchall()


_PAGE_ORDERS = {
    "latest": ("id DESC", None, None),
    "archive": ("id ASC", None, None),
    "size_desc": ("media_size DESC, id DESC", "media_size", "DESC"),
    "duration_desc": ("duration_s DESC, id DESC", "duration_s", "DESC"),
    "duration_asc": ("duration_s ASC, id ASC", "duration_s", "ASC"),
    "favorite_date_desc": ("favorited_at DESC, id DESC", "favorited_at", "DESC"),
    "favorite_date_asc": ("favorited_at ASC, id ASC", "favorited_at", "ASC"),
    "relevance": ("rank ASC, id DESC", None, None),
}


def page_items(
    conn,
    query=None,
    kinds=None,
    statuses=None,
    limit=50,
    cursor=None,
    order="latest",
    min_duration=None,
    max_duration=None,
    min_size=None,
    max_size=None,
    date_from=None,
    date_to=None,
    orientations=None,
    include=None,
    exclude=None,
):
    """Return one cursor page without materializing the whole Archive library."""
    clauses, params = _item_filters(kinds=kinds, statuses=statuses)
    fts_query = _fts_query(query)
    if min_duration is not None:
        clauses.append("duration_s >= ?")
        params.append(float(min_duration))
    if max_duration is not None:
        clauses.append("duration_s <= ?")
        params.append(float(max_duration))
    if min_size is not None:
        clauses.append("media_size >= ?")
        params.append(int(min_size))
    if max_size is not None:
        clauses.append("media_size <= ?")
        params.append(int(max_size))
    if date_from:
        clauses.append("favorited_at >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("favorited_at <= ?")
        params.append(date_to)
    if orientations:
        orientation_sql = {
            "portrait": "media_height > media_width",
            "landscape": "media_width > media_height",
            "square": "media_width = media_height",
        }
        selected = [orientation_sql[name] for name in orientations if name in orientation_sql]
        if selected:
            clauses.append("(" + " OR ".join(selected) + ")")
    for term in include or []:
        clauses.append("(caption LIKE ? OR author LIKE ?)")
        params += [f"%{term}%", f"%{term}%"]
    for term in exclude or []:
        clauses.append("NOT (caption LIKE ? OR author LIKE ?)")
        params += [f"%{term}%", f"%{term}%"]
    if fts_query and order == "latest":
        order = "relevance"
    if order not in _PAGE_ORDERS:
        raise ValueError(f"unknown item order: {order}")
    order_sql, field, direction = _PAGE_ORDERS[order]
    if cursor is not None:
        if order == "relevance":
            cursor_row = conn.execute(
                "WITH matched AS (SELECT item.id, bm25(item_search) AS rank FROM item_search JOIN item ON item_search.rowid = item.id WHERE item_search MATCH ?) SELECT rank FROM matched WHERE id = ?",
                (fts_query, int(cursor)),
            ).fetchone()
            if cursor_row is None:
                raise ValueError("unknown pagination cursor")
            clauses.append("(rank > ? OR (rank = ? AND id < ?))")
            params += [cursor_row["rank"], cursor_row["rank"], int(cursor)]
        else:
            cursor_row = get_item(conn, int(cursor))
            if cursor_row is None:
                raise ValueError("unknown pagination cursor")
            if field is None:
                comparator = "<" if order == "latest" else ">"
                clauses.append(f"id {comparator} ?")
                params.append(int(cursor))
            else:
                cursor_value = cursor_row[field]
                if cursor_value is None:
                    raise ValueError("cursor cannot be used for an unindexed item")
                comparator = "<" if direction == "DESC" else ">"
                clauses.append(f"({field} {comparator} ? OR ({field} = ? AND id {comparator} ?))")
                params += [cursor_value, cursor_value, int(cursor)]
    if field is not None:
        clauses.append(f"{field} IS NOT NULL")
    if fts_query:
        sql = "WITH matched AS (SELECT item.*, bm25(item_search) AS rank FROM item_search JOIN item ON item_search.rowid = item.id WHERE item_search MATCH ?) SELECT * FROM matched"
        params = [fts_query, *params]
    else:
        sql = "SELECT * FROM item"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += f" ORDER BY {order_sql} LIMIT ?"
    params.append(max(1, min(int(limit), 100)))
    return conn.execute(sql, params).fetchall()


def window_items(conn, item_id, limit=50):
    """Return the selected Favorite then its older archive neighbors."""
    return conn.execute(
        "SELECT * FROM item WHERE id <= ? ORDER BY id DESC LIMIT ?",
        (item_id, max(1, min(int(limit), 100))),
    ).fetchall()


def playable_item_ids(conn):
    return [row["id"] for row in conn.execute("SELECT id FROM item WHERE status = 'done' ORDER BY id").fetchall()]


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


def get_library_settings(conn):
    return conn.execute("SELECT * FROM library_settings WHERE id = 1").fetchone()


def library_index_status(conn):
    """Summarize durable Gallery-index coverage for the Sync screen."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN thumbnail_path IS NOT NULL THEN 1 ELSE 0 END) AS indexed,
            SUM(CASE WHEN thumbnail_path IS NULL THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN thumbnail_path IS NULL AND index_error IS NOT NULL THEN 1 ELSE 0 END) AS failed
        FROM item
        WHERE status = 'done'
        """
    ).fetchone()
    return {name: int(row[name] or 0) for name in ("total", "indexed", "pending", "failed")}


def set_library_settings(conn, index_enabled=None, thumbnail_width=None):
    fields = {}
    if index_enabled is not None:
        fields["index_enabled"] = 1 if index_enabled else 0
    if thumbnail_width is not None:
        if thumbnail_width not in (320, 480):
            raise ValueError("thumbnail width must be 320 or 480")
        fields["thumbnail_width"] = thumbnail_width
    if not fields:
        return
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{name} = ?" for name in fields)
    conn.execute(f"UPDATE library_settings SET {assignments} WHERE id = 1", tuple(fields.values()))
    conn.commit()


# --- saved Gallery filters -------------------------------------------------

def list_gallery_presets(conn):
    rows = conn.execute("SELECT id, name, filters_json FROM gallery_preset ORDER BY name COLLATE NOCASE, id").fetchall()
    return [{"id": row["id"], "name": row["name"], "filters": json.loads(row["filters_json"])} for row in rows]


def save_gallery_preset(conn, name, filters):
    cursor = conn.execute(
        "INSERT INTO gallery_preset (name, filters_json, created_at) VALUES (?, ?, ?)",
        (name, json.dumps(filters, separators=(",", ":"), sort_keys=True), _now()),
    )
    conn.commit()
    return cursor.lastrowid


def delete_gallery_preset(conn, preset_id):
    cursor = conn.execute("DELETE FROM gallery_preset WHERE id = ?", (preset_id,))
    conn.commit()
    return cursor.rowcount > 0
