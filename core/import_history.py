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


# A favorite dropped from an export is "safely archived" when the media is
# still readable locally, or when a verified copy sits on a managed location.
_PROTECTED = (
    "(item.status = 'done' AND item.offloaded = 0 AND item.archive_missing = 0) "
    "OR EXISTS ("
    "SELECT 1 FROM media_placement placement "
    "WHERE placement.item_id = item.id "
    "AND placement.verified = 1 AND placement.is_active = 1"
    ")"
)


def _membership_count(conn, import_id):
    return conn.execute(
        "SELECT COUNT(*) AS count FROM import_membership WHERE import_id = ?",
        (import_id,),
    ).fetchone()["count"]


def _changed_entries(conn, present_id, absent_id, limit, *, protection=False):
    """Favorites recorded in `present_id` whose links are absent from `absent_id`.

    The diff stays in SQLite: an export holds tens of thousands of memberships
    but a page only ever shows `limit` of them, so reading both sides into
    Python to subtract them costs far more than it returns.
    """
    joins = ""
    conditions = ""
    params = []
    if absent_id is not None:
        joins = (
            "LEFT JOIN import_membership absent "
            "ON absent.import_id = ? AND absent.link = present.link "
        )
        conditions = " AND absent.link IS NULL"
        params.append(absent_id)
    params.extend((present_id, limit))
    query = (
        "SELECT present.item_id AS item_id, present.link AS link, "
        "present.favorited_at AS favorited_at "
        f"FROM import_membership present {joins}"
        f"WHERE present.import_id = ?{conditions} "
        "ORDER BY present.item_id, present.link LIMIT ?"
    )
    if protection:
        # Archive health is resolved for the page-sized slice only. Joining
        # item before the limit would drag every membership row through it.
        query = (
            f"SELECT changed.*, CASE WHEN {_PROTECTED} THEN 1 ELSE 0 END AS protected "
            f"FROM ({query}) changed JOIN item ON item.id = changed.item_id "
            "ORDER BY changed.item_id, changed.link"
        )
    rows = conn.execute(query, tuple(params)).fetchall()
    entries = []
    for row in rows:
        entry = {
            "item_id": row["item_id"],
            "link": row["link"],
            "favorited_at": row["favorited_at"],
        }
        if protection:
            entry["protected"] = bool(row["protected"])
        entries.append(entry)
    return entries


def _comparison(conn, current_id, previous_id, change_limit=200):
    limit = max(1, min(int(change_limit), 1_000))
    counts = _comparison_counts(conn, current_id, previous_id)
    # The counts already settle whether a side has anything in it, so an
    # export that only gained favorites never runs the removed-side diff.
    return {
        "counts": counts,
        "new": (
            _changed_entries(conn, current_id, previous_id, limit)
            if counts["new"] else []
        ),
        "removed": (
            _changed_entries(conn, previous_id, current_id, limit, protection=True)
            if counts["removed"] else []
        ),
        "truncated": counts["new"] > limit or counts["removed"] > limit,
    }


def _protected_count(conn, current_id, previous_id):
    return conn.execute(
        "SELECT COUNT(*) AS count FROM import_membership previous "
        "LEFT JOIN import_membership current "
        "ON current.import_id = ? AND current.link = previous.link "
        "JOIN item ON item.id = previous.item_id "
        f"WHERE previous.import_id = ? AND current.link IS NULL AND ({_PROTECTED})",
        (current_id, previous_id),
    ).fetchone()["count"]


def _comparison_counts(conn, current_id, previous_id):
    current_total = _membership_count(conn, current_id)
    if previous_id is None:
        return {
            "new": current_total,
            "removed": 0,
            "unchanged": 0,
            "protected": 0,
        }
    # Links are unique per import, so one overlap count settles all three
    # totals — no anti-join needed for the two sides that only add rows.
    unchanged = conn.execute(
        "SELECT COUNT(*) AS count FROM import_membership current "
        "JOIN import_membership previous "
        "ON previous.import_id = ? AND previous.link = current.link "
        "WHERE current.import_id = ?",
        (previous_id, current_id),
    ).fetchone()["count"]
    removed = _membership_count(conn, previous_id) - unchanged
    return {
        "new": current_total - unchanged,
        "removed": removed,
        "unchanged": unchanged,
        # Only a dropped favorite can be protected, so an export that only
        # gained favorites skips the item join entirely.
        "protected": (
            _protected_count(conn, current_id, previous_id) if removed else 0
        ),
    }


def _row_record(row):
    return {
        "id": row["id"],
        "source_name": row["source_name"],
        "selection": row["selection"],
        "digest": row["digest"],
        "favorite_count": row["favorite_count"],
        "imported_at": row["imported_at"],
    }


def record_import(conn, favorites, source_name=None, selection="favorites"):
    previous = conn.execute(
        "SELECT id FROM import_history WHERE selection = ? ORDER BY id DESC LIMIT 1",
        (selection,),
    ).fetchone()
    previous_id = previous["id"] if previous is not None else None
    imported_at = _now()
    conn.execute("SAVEPOINT record_import")
    try:
        cursor = conn.execute(
            "INSERT INTO import_history "
            "(source_name, selection, digest, favorite_count, imported_at) VALUES (?, ?, ?, ?, ?)",
            (_source_name(source_name), selection, _digest(favorites), len(favorites), imported_at),
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


def list_imports(conn, limit=50, change_limit=200):
    limit = max(1, min(int(limit), 200))
    rows = conn.execute(
        "SELECT * FROM import_history ORDER BY id DESC LIMIT ?", (limit,),
    ).fetchall()
    records = []
    for index, row in enumerate(rows):
        previous = conn.execute(
            "SELECT id FROM import_history WHERE id < ? AND selection = ? ORDER BY id DESC LIMIT 1",
            (row["id"], row["selection"]),
        ).fetchone()
        previous_id = previous["id"] if previous is not None else None
        records.append({
            **_row_record(row),
            "previous_id": previous_id,
            # The newest checkpoint is the one a reader opens on, so its full
            # diff rides along and spares the client a second round trip.
            "comparison": (
                _comparison(conn, row["id"], previous_id, change_limit=change_limit)
                if index == 0
                else {"counts": _comparison_counts(conn, row["id"], previous_id)}
            ),
        })
    return records


def get_import(conn, import_id, change_limit=200):
    row = conn.execute(
        "SELECT * FROM import_history WHERE id = ?", (int(import_id),),
    ).fetchone()
    if row is None:
        return None
    previous = conn.execute(
        "SELECT id FROM import_history WHERE id < ? AND selection = ? ORDER BY id DESC LIMIT 1",
        (row["id"], row["selection"]),
    ).fetchone()
    previous_id = previous["id"] if previous is not None else None
    return {
        **_row_record(row),
        "previous_id": previous_id,
        "comparison": _comparison(
            conn, row["id"], previous_id, change_limit=change_limit,
        ),
    }
