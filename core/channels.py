"""Saved continuous-play channels backed by live Gallery Smart Collections."""
import random
from datetime import datetime

from core import selection


def _now():
    return datetime.now().isoformat(timespec="seconds")


def parse_channel(body):
    if not isinstance(body, dict):
        raise ValueError("channel must be an object")
    name = body.get("name")
    preset_id = body.get("preset_id")
    shuffle = body.get("shuffle", False)
    prefer_unwatched = body.get("prefer_unwatched", True)
    if not isinstance(name, str) or not (name := name.strip()) or len(name) > 80:
        raise ValueError("name must be between 1 and 80 characters")
    if type(preset_id) is not int or preset_id < 1:
        raise ValueError("preset_id must be a positive integer")
    if not isinstance(shuffle, bool) or not isinstance(prefer_unwatched, bool):
        raise ValueError("shuffle and prefer_unwatched must be booleans")
    return {
        "name": name,
        "preset_id": preset_id,
        "shuffle": shuffle,
        "prefer_unwatched": prefer_unwatched,
    }


def _public(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "preset_id": row["preset_id"],
        "preset_name": row["preset_name"],
        "shuffle": bool(row["shuffle"]),
        "prefer_unwatched": bool(row["prefer_unwatched"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_channels(conn):
    return [
        _public(row) for row in conn.execute(
            "SELECT c.*, p.name AS preset_name FROM archive_channel c "
            "JOIN gallery_preset p ON p.id = c.preset_id "
            "ORDER BY c.name COLLATE NOCASE, c.id"
        )
    ]


def get_channel(conn, channel_id):
    row = conn.execute(
        "SELECT c.*, p.name AS preset_name FROM archive_channel c "
        "JOIN gallery_preset p ON p.id = c.preset_id WHERE c.id = ?",
        (channel_id,),
    ).fetchone()
    return None if row is None else _public(row)


def create(conn, body):
    parsed = parse_channel(body)
    if conn.execute(
        "SELECT 1 FROM gallery_preset WHERE id = ?", (parsed["preset_id"],),
    ).fetchone() is None:
        raise KeyError(parsed["preset_id"])
    now = _now()
    cursor = conn.execute(
        "INSERT INTO archive_channel "
        "(name, preset_id, shuffle, prefer_unwatched, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            parsed["name"], parsed["preset_id"], int(parsed["shuffle"]),
            int(parsed["prefer_unwatched"]), now, now,
        ),
    )
    conn.commit()
    return get_channel(conn, cursor.lastrowid)


def delete(conn, channel_id):
    cursor = conn.execute("DELETE FROM archive_channel WHERE id = ?", (channel_id,))
    conn.commit()
    return bool(cursor.rowcount)


def item_ids(conn, channel_id, query_from_filters):
    channel = get_channel(conn, channel_id)
    if channel is None:
        raise KeyError(channel_id)
    _preset, chosen = selection.ArchiveSelection.smart_collection(
        conn, channel["preset_id"], scope="feed",
        query_from_filters=query_from_filters,
    )
    ids = chosen.ids(conn)
    playable = {
        row["id"] for row in conn.execute(
            "SELECT id FROM item WHERE status = 'done' AND offloaded = 0 "
            "AND archive_missing = 0"
        )
    }
    ids = [
        item_id for item_id in ids
        if item_id in playable
    ]
    if channel["shuffle"]:
        random.Random(channel["id"]).shuffle(ids)
    if channel["prefer_unwatched"] and ids:
        watched = {
            row["item_id"] for row in conn.execute(
                "SELECT item_id FROM item_play",
            )
        }
        ids.sort(key=lambda item_id: item_id in watched)
    return channel, ids
