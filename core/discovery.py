"""Canonical Creator/Hashtag identities, exact queries, and resumable backfill."""
from datetime import datetime, timezone
import re
import unicodedata

from core import migrations


BACKFILL = "discovery-identities-v1"
_HASHTAG = re.compile(r"(?<![\w#])#([^\W_][\w·-]*)", re.UNICODE)


def normalize(value, prefix):
    if not isinstance(value, str):
        return ""
    display = unicodedata.normalize("NFKC", value).strip()
    if display.startswith(prefix):
        display = display[1:]
    return display.strip().casefold()


def normalize_creator(value):
    return normalize(value, "@")


def normalize_hashtag(value):
    return normalize(value, "#")


def extract_hashtags(caption):
    """Unique hashtags in caption order, preserving normalized display spelling."""
    if not isinstance(caption, str):
        return []
    found = []
    seen = set()
    for match in _HASHTAG.finditer(unicodedata.normalize("NFKC", caption)):
        display = "#" + match.group(1)
        key = normalize_hashtag(display)
        if key and key not in seen:
            seen.add(key)
            found.append((key, display))
    return found


def _upsert(conn, table, key, display):
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        f"INSERT INTO {table}(canonical_key, display_name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(canonical_key) DO UPDATE SET "
        "display_name = CASE WHEN length(excluded.display_name) > length(display_name) "
        "THEN excluded.display_name ELSE display_name END, updated_at = excluded.updated_at",
        (key, display, now, now),
    )
    return conn.execute(
        f"SELECT id FROM {table} WHERE canonical_key = ?", (key,),
    ).fetchone()["id"]


def upsert_item_identities(conn, item_id, author, caption):
    creator_key = normalize_creator(author)
    creator_id = None
    if creator_key:
        creator_id = _upsert(conn, "creator", creator_key, unicodedata.normalize("NFKC", author).strip())
    conn.execute("UPDATE item SET creator_id = ? WHERE id = ?", (creator_id, item_id))
    conn.execute("DELETE FROM item_hashtag WHERE item_id = ?", (item_id,))
    for key, display in extract_hashtags(caption):
        hashtag_id = _upsert(conn, "hashtag", key, display)
        conn.execute(
            "INSERT OR IGNORE INTO item_hashtag(item_id, hashtag_id) VALUES (?, ?)",
            (item_id, hashtag_id),
        )


def ensure_backfill(conn):
    total = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    return migrations.ensure_backfill(conn, BACKFILL, total)


def run_backfill(conn, _download_dir, control=None, batch_size=200):
    state = ensure_backfill(conn)
    if state["status"] == "completed":
        return {"processed": state["processed"], "total": state["total"]}
    migrations.start_backfill(conn, BACKFILL)
    cursor = int(state["cursor"] or 0)
    processed = int(state["processed"])
    total = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    while True:
        rows = conn.execute(
            "SELECT id, author, caption FROM item WHERE id > ? ORDER BY id LIMIT ?",
            (cursor, max(1, min(int(batch_size), 1000))),
        ).fetchall()
        if not rows:
            migrations.complete_backfill(conn, BACKFILL)
            return {"processed": processed, "total": total}
        for row in rows:
            if control is not None and not control.should_continue():
                return {"processed": processed, "total": total}
            with conn:
                upsert_item_identities(conn, row["id"], row["author"], row["caption"])
            cursor = row["id"]
            processed += 1
        migrations.update_backfill(
            conn, BACKFILL, cursor=cursor, processed=processed, total=total,
        )
        if control is not None:
            control.progress({
                "event": "discovery", "completed": processed, "total": total,
            })


def identities_for_items(conn, item_ids):
    ids = sorted({int(item_id) for item_id in item_ids})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    result = {
        item_id: {"creator": None, "hashtags": []} for item_id in ids
    }
    for row in conn.execute(
        f"SELECT i.id AS item_id, c.id, c.canonical_key, c.display_name "
        f"FROM item i LEFT JOIN creator c ON c.id = i.creator_id "
        f"WHERE i.id IN ({placeholders})", ids,
    ):
        if row["id"] is not None:
            result[row["item_id"]]["creator"] = {
                "id": row["id"], "key": row["canonical_key"],
                "display": row["display_name"],
            }
    for row in conn.execute(
        f"SELECT ih.item_id, h.id, h.canonical_key, h.display_name "
        f"FROM item_hashtag ih JOIN hashtag h ON h.id = ih.hashtag_id "
        f"WHERE ih.item_id IN ({placeholders}) ORDER BY ih.item_id, h.id", ids,
    ):
        result[row["item_id"]]["hashtags"].append({
            "id": row["id"], "key": row["canonical_key"],
            "display": row["display_name"],
        })
    return result


def _trend(conn, kind, entity_id, months=12):
    relation = (
        "item i WHERE i.creator_id = ?"
        if kind == "creator"
        else "item_hashtag rel JOIN item i ON i.id = rel.item_id WHERE rel.hashtag_id = ?"
    )
    rows = conn.execute(
        "SELECT substr(i.favorited_at, 1, 7) AS month, COUNT(*) AS count "
        f"FROM {relation} AND i.favorited_at IS NOT NULL "
        "GROUP BY month ORDER BY month DESC LIMIT ?",
        (entity_id, max(1, min(int(months), 24))),
    ).fetchall()
    return [{"month": row["month"], "count": row["count"]} for row in reversed(rows)]


def list_entities(conn, kind, *, search="", order="frequency", cursor=0, limit=50):
    if kind == "creator":
        table = "creator"
        count_sql = "(SELECT COUNT(*) FROM item i WHERE i.creator_id = e.id)"
        latest_sql = "(SELECT MAX(favorited_at) FROM item i WHERE i.creator_id = e.id)"
        first_sql = "(SELECT id FROM item i WHERE i.creator_id = e.id ORDER BY favorite_order DESC, id DESC LIMIT 1)"
    elif kind == "hashtag":
        table = "hashtag"
        count_sql = "(SELECT COUNT(*) FROM item_hashtag ih WHERE ih.hashtag_id = e.id)"
        latest_sql = "(SELECT MAX(i.favorited_at) FROM item_hashtag ih JOIN item i ON i.id = ih.item_id WHERE ih.hashtag_id = e.id)"
        first_sql = "(SELECT i.id FROM item_hashtag ih JOIN item i ON i.id = ih.item_id WHERE ih.hashtag_id = e.id ORDER BY i.favorite_order DESC, i.id DESC LIMIT 1)"
    else:
        raise ValueError("unknown discovery resource")
    if order not in ("frequency", "trend", "name"):
        raise ValueError("order must be frequency, trend, or name")
    cursor = max(0, int(cursor))
    limit = max(1, min(int(limit), 100))
    ordering = {
        "frequency": "use_count DESC, e.display_name COLLATE NOCASE, e.id",
        "trend": "latest_at DESC, use_count DESC, e.id",
        "name": "e.display_name COLLATE NOCASE, e.id",
    }[order]
    needle = f"%{normalize(search, '@' if kind == 'creator' else '#')}%"
    rows = conn.execute(
        f"SELECT e.*, {count_sql} AS use_count, {latest_sql} AS latest_at, {first_sql} AS first_item_id "
        f"FROM {table} e WHERE e.canonical_key LIKE ? ORDER BY {ordering} LIMIT ? OFFSET ?",
        (needle, limit + 1, cursor),
    ).fetchall()
    items = [
        {
            "id": row["id"], "key": row["canonical_key"],
            "display": row["display_name"], "count": row["use_count"],
            "latest_at": row["latest_at"], "first_item_id": row["first_item_id"],
        }
        for row in rows[:limit]
    ]
    return {"items": items, "next_cursor": cursor + limit if len(rows) > limit else None}


def get_entity(conn, kind, entity_id):
    if kind == "creator":
        table = "creator"
        count_sql = "(SELECT COUNT(*) FROM item i WHERE i.creator_id = e.id)"
        latest_sql = "(SELECT MAX(favorited_at) FROM item i WHERE i.creator_id = e.id)"
        first_sql = "(SELECT id FROM item i WHERE i.creator_id = e.id ORDER BY favorite_order DESC, id DESC LIMIT 1)"
    elif kind == "hashtag":
        table = "hashtag"
        count_sql = "(SELECT COUNT(*) FROM item_hashtag ih WHERE ih.hashtag_id = e.id)"
        latest_sql = "(SELECT MAX(i.favorited_at) FROM item_hashtag ih JOIN item i ON i.id = ih.item_id WHERE ih.hashtag_id = e.id)"
        first_sql = "(SELECT i.id FROM item_hashtag ih JOIN item i ON i.id = ih.item_id WHERE ih.hashtag_id = e.id ORDER BY i.favorite_order DESC, i.id DESC LIMIT 1)"
    else:
        raise ValueError("unknown discovery resource")
    row = conn.execute(
        f"SELECT e.*, {count_sql} AS use_count, {latest_sql} AS latest_at, {first_sql} AS first_item_id "
        f"FROM {table} e WHERE e.id = ?", (entity_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"], "key": row["canonical_key"],
        "display": row["display_name"], "count": row["use_count"],
        "latest_at": row["latest_at"], "first_item_id": row["first_item_id"],
        "trend": _trend(conn, kind, entity_id),
    }
