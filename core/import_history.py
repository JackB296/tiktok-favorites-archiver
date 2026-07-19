"""Immutable TikTok export provenance and adjacent-import comparison."""
from datetime import datetime
import hashlib
import json

from core import store


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _source_name(value):
    if not isinstance(value, str):
        return "TikTok export"
    display = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return (display or "TikTok export")[:160]


def _digest(favorites):
    encoded = json.dumps(
        favorites, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _membership(conn, import_id):
    if import_id is None:
        return {}
    rows = conn.execute(
        "SELECT item_id, link, favorited_at FROM import_membership "
        "WHERE import_id = ? ORDER BY item_id",
        (import_id,),
    ).fetchall()
    return {
        row["link"]: {
            "item_id": row["item_id"],
            "link": row["link"],
            "favorited_at": row["favorited_at"],
        }
        for row in rows
    }


def _protected_item_ids(conn, item_ids):
    protected = set()
    ids = list(dict.fromkeys(int(item_id) for item_id in item_ids))
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            "SELECT DISTINCT item.id FROM item "
            "LEFT JOIN media_placement placement "
            "ON placement.item_id = item.id "
            "AND placement.verified = 1 AND placement.is_active = 1 "
            f"WHERE item.id IN ({placeholders}) AND ("
            "(item.status = 'done' AND item.offloaded = 0 AND item.archive_missing = 0) "
            "OR placement.id IS NOT NULL"
            ")",
            chunk,
        ).fetchall()
        protected.update(row["id"] for row in rows)
    return protected


def _comparison(conn, current_id, previous_id, change_limit=200):
    current = _membership(conn, current_id)
    previous = _membership(conn, previous_id)
    new_links = current.keys() - previous.keys()
    removed_links = previous.keys() - current.keys()
    new = sorted(
        (current[link] for link in new_links),
        key=lambda entry: (entry["item_id"], entry["link"]),
    )
    removed = sorted(
        (previous[link] for link in removed_links),
        key=lambda entry: (entry["item_id"], entry["link"]),
    )
    protected_ids = _protected_item_ids(
        conn, [entry["item_id"] for entry in removed],
    )
    for entry in removed:
        entry["protected"] = entry["item_id"] in protected_ids
    protected = sum(1 for entry in removed if entry["protected"])
    limit = max(1, min(int(change_limit), 1_000))
    return {
        "counts": {
            "new": len(new),
            "removed": len(removed),
            "unchanged": len(current.keys() & previous.keys()),
            "protected": protected,
        },
        "new": new[:limit],
        "removed": removed[:limit],
        "truncated": len(new) > limit or len(removed) > limit,
    }


def _comparison_counts(conn, current_id, previous_id):
    if previous_id is None:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM import_membership WHERE import_id = ?",
            (current_id,),
        ).fetchone()
        return {
            "new": row["count"],
            "removed": 0,
            "unchanged": 0,
            "protected": 0,
        }
    row = conn.execute(
        "SELECT "
        "SUM(CASE WHEN previous.link IS NULL THEN 1 ELSE 0 END) AS new_count, "
        "SUM(CASE WHEN previous.link IS NOT NULL THEN 1 ELSE 0 END) AS unchanged_count "
        "FROM import_membership current "
        "LEFT JOIN import_membership previous "
        "ON previous.import_id = ? AND previous.link = current.link "
        "WHERE current.import_id = ?",
        (previous_id, current_id),
    ).fetchone()
    removed = conn.execute(
        "SELECT COUNT(*) AS removed_count, "
        "COALESCE(SUM(CASE WHEN ("
        "(item.status = 'done' AND item.offloaded = 0 AND item.archive_missing = 0) "
        "OR EXISTS ("
        "SELECT 1 FROM media_placement placement "
        "WHERE placement.item_id = item.id "
        "AND placement.verified = 1 AND placement.is_active = 1"
        ")) "
        "THEN 1 ELSE 0 END), 0) AS protected_count "
        "FROM import_membership previous "
        "LEFT JOIN import_membership current "
        "ON current.import_id = ? AND current.link = previous.link "
        "JOIN item ON item.id = previous.item_id "
        "WHERE previous.import_id = ? AND current.link IS NULL",
        (current_id, previous_id),
    ).fetchone()
    return {
        "new": row["new_count"] or 0,
        "removed": removed["removed_count"] or 0,
        "unchanged": row["unchanged_count"] or 0,
        "protected": removed["protected_count"] or 0,
    }


def _row_record(row):
    return {
        "id": row["id"],
        "source_name": row["source_name"],
        "digest": row["digest"],
        "favorite_count": row["favorite_count"],
        "imported_at": row["imported_at"],
    }


def record_import(conn, favorites, source_name=None):
    previous = conn.execute(
        "SELECT id FROM import_history ORDER BY id DESC LIMIT 1"
    ).fetchone()
    previous_id = previous["id"] if previous is not None else None
    imported_at = _now()
    conn.execute("SAVEPOINT record_import")
    try:
        cursor = conn.execute(
            "INSERT INTO import_history "
            "(source_name, digest, favorite_count, imported_at) VALUES (?, ?, ?, ?)",
            (_source_name(source_name), _digest(favorites), len(favorites), imported_at),
        )
        import_id = cursor.lastrowid
        memberships = {}
        for link, favorited_at in favorites:
            item = store.get_item_by_link(conn, link)
            if item is None:
                raise RuntimeError(f"imported favorite has no Archive item: {link}")
            if link not in memberships or (
                memberships[link][3] is None and favorited_at is not None
            ):
                memberships[link] = (
                    import_id, item["id"], link, favorited_at,
                )
        conn.executemany(
            "INSERT INTO import_membership "
            "(import_id, item_id, link, favorited_at) VALUES (?, ?, ?, ?)",
            memberships.values(),
        )
        conn.execute("RELEASE record_import")
    except Exception:
        conn.execute("ROLLBACK TO record_import")
        conn.execute("RELEASE record_import")
        raise
    row = conn.execute(
        "SELECT * FROM import_history WHERE id = ?", (import_id,),
    ).fetchone()
    return {
        **_row_record(row),
        "previous_id": previous_id,
        "comparison": _comparison(conn, import_id, previous_id),
    }


def list_imports(conn, limit=50):
    limit = max(1, min(int(limit), 200))
    rows = conn.execute(
        "SELECT * FROM import_history ORDER BY id DESC LIMIT ?", (limit,),
    ).fetchall()
    records = []
    for row in rows:
        previous = conn.execute(
            "SELECT id FROM import_history WHERE id < ? ORDER BY id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        previous_id = previous["id"] if previous is not None else None
        records.append({
            **_row_record(row),
            "previous_id": previous_id,
            "comparison": {
                "counts": _comparison_counts(conn, row["id"], previous_id),
            },
        })
    return records


def get_import(conn, import_id, change_limit=200):
    row = conn.execute(
        "SELECT * FROM import_history WHERE id = ?", (int(import_id),),
    ).fetchone()
    if row is None:
        return None
    previous = conn.execute(
        "SELECT id FROM import_history WHERE id < ? ORDER BY id DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    previous_id = previous["id"] if previous is not None else None
    return {
        **_row_record(row),
        "previous_id": previous_id,
        "comparison": _comparison(
            conn, row["id"], previous_id, change_limit=change_limit,
        ),
    }
