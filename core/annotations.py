"""Private curation metadata and bounded review sessions."""
import re
import unicodedata
from datetime import datetime


MAX_NOTE_LENGTH = 2000
MAX_TAGS = 20
MAX_TAG_LENGTH = 50


def _now():
    return datetime.now().isoformat(timespec="seconds")


def normalize_tag(value):
    """Stable private-tag key; display spelling remains user controlled."""
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.casefold()


def parse_annotation(body):
    if not isinstance(body, dict):
        raise ValueError("annotation must be an object")
    starred = body.get("starred", False)
    reviewed = body.get("reviewed", False)
    note = body.get("note", "")
    tags = body.get("tags", [])
    if not isinstance(starred, bool):
        raise ValueError("starred must be a boolean")
    if not isinstance(reviewed, bool):
        raise ValueError("reviewed must be a boolean")
    if not isinstance(note, str) or len(note) > MAX_NOTE_LENGTH:
        raise ValueError(f"note must be at most {MAX_NOTE_LENGTH} characters")
    if not isinstance(tags, list) or len(tags) > MAX_TAGS:
        raise ValueError(f"tags must contain at most {MAX_TAGS} entries")
    cleaned = []
    seen = set()
    for tag in tags:
        if not isinstance(tag, str):
            raise ValueError("each tag must be text")
        display = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", tag).strip())
        key = normalize_tag(display)
        if not key or len(display) > MAX_TAG_LENGTH:
            raise ValueError(f"each tag must be 1 to {MAX_TAG_LENGTH} characters")
        if key not in seen:
            cleaned.append((key, display))
            seen.add(key)
    return {
        "starred": starred,
        "note": note.strip(),
        "reviewed": reviewed,
        "tags": cleaned,
    }


def empty(item_id):
    return {
        "item_id": int(item_id),
        "starred": False,
        "note": "",
        "tags": [],
        "reviewed": False,
        "reviewed_at": None,
        "updated_at": None,
    }


def for_items(conn, item_ids):
    ids = sorted({int(item_id) for item_id in item_ids})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    values = {item_id: empty(item_id) for item_id in ids}
    for row in conn.execute(
        f"SELECT item_id, starred, note, reviewed_at, updated_at "
        f"FROM item_annotation WHERE item_id IN ({placeholders})",
        ids,
    ):
        values[row["item_id"]].update({
            "starred": bool(row["starred"]),
            "note": row["note"],
            "reviewed": row["reviewed_at"] is not None,
            "reviewed_at": row["reviewed_at"],
            "updated_at": row["updated_at"],
        })
    for row in conn.execute(
        f"SELECT ipt.item_id, pt.display_name FROM item_private_tag ipt "
        f"JOIN private_tag pt ON pt.id = ipt.tag_id "
        f"WHERE ipt.item_id IN ({placeholders}) "
        f"ORDER BY pt.display_name COLLATE NOCASE, pt.id",
        ids,
    ):
        values[row["item_id"]]["tags"].append(row["display_name"])
    return values


def get(conn, item_id):
    if conn.execute("SELECT 1 FROM item WHERE id = ?", (item_id,)).fetchone() is None:
        return None
    return for_items(conn, [item_id])[int(item_id)]


def save(conn, item_id, body):
    parsed = parse_annotation(body)
    existing = get(conn, item_id)
    if existing is None:
        raise KeyError(item_id)
    now = _now()
    reviewed_at = (
        existing["reviewed_at"] if parsed["reviewed"] and existing["reviewed_at"]
        else now if parsed["reviewed"]
        else None
    )
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO item_annotation "
            "(item_id, starred, note, reviewed_at, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(item_id) DO UPDATE SET starred = excluded.starred, "
            "note = excluded.note, reviewed_at = excluded.reviewed_at, "
            "updated_at = excluded.updated_at",
            (item_id, int(parsed["starred"]), parsed["note"], reviewed_at, now),
        )
        tag_ids = []
        for key, display in parsed["tags"]:
            conn.execute(
                "INSERT INTO private_tag "
                "(canonical_key, display_name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(canonical_key) DO UPDATE SET "
                "display_name = excluded.display_name, updated_at = excluded.updated_at",
                (key, display, now, now),
            )
            tag_ids.append(conn.execute(
                "SELECT id FROM private_tag WHERE canonical_key = ?", (key,),
            ).fetchone()["id"])
        conn.execute("DELETE FROM item_private_tag WHERE item_id = ?", (item_id,))
        conn.executemany(
            "INSERT INTO item_private_tag (item_id, tag_id) VALUES (?, ?)",
            [(item_id, tag_id) for tag_id in tag_ids],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get(conn, item_id)


def session_rows(conn, source="unreviewed", limit=20):
    if source not in ("unreviewed", "forgotten"):
        raise ValueError("source must be unreviewed or forgotten")
    limit = int(limit)
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    where = []
    if source == "unreviewed":
        where.append("(ia.reviewed_at IS NULL)")
        order = "item.favorite_order DESC, item.id DESC"
    else:
        order = (
            "CASE WHEN ip.last_played_at IS NULL THEN 0 ELSE 1 END, "
            "ip.last_played_at ASC, item.favorite_order ASC, item.id ASC"
        )
    return conn.execute(
        "SELECT item.* FROM item "
        "LEFT JOIN item_annotation ia ON ia.item_id = item.id "
        "LEFT JOIN item_play ip ON ip.item_id = item.id "
        f"{'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY {order} LIMIT ?",
        (limit,),
    ).fetchall()
