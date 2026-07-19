"""Private play history and deterministic archive resurfacing."""
from datetime import date, datetime

from core import store


class MemoryError(ValueError):
    pass


def _timestamp(value=None):
    if value is None:
        return datetime.now().isoformat(timespec="seconds")
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise MemoryError("play time must be an ISO timestamp") from exc
        return parsed.isoformat(timespec="seconds")
    raise MemoryError("play time must be an ISO timestamp")


def _date(value=None):
    if value is None:
        return date.today()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise MemoryError("date must use YYYY-MM-DD") from exc
    raise MemoryError("date must use YYYY-MM-DD")


def _play_row(row):
    return {
        "item_id": row["item_id"],
        "play_count": row["play_count"],
        "first_played_at": row["first_played_at"],
        "last_played_at": row["last_played_at"],
    }


def record_play(conn, item_id, at=None):
    if store.get_item(conn, int(item_id)) is None:
        raise MemoryError("favorite not found")
    played_at = _timestamp(at)
    conn.execute(
        "INSERT INTO item_play "
        "(item_id, play_count, first_played_at, last_played_at) "
        "VALUES (?, 1, ?, ?) "
        "ON CONFLICT(item_id) DO UPDATE SET "
        "play_count = item_play.play_count + 1, last_played_at = excluded.last_played_at",
        (int(item_id), played_at, played_at),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM item_play WHERE item_id = ?", (int(item_id),),
    ).fetchone()
    return _play_row(row)


def _parse_favorite_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def build_sections(conn, on_date=None, limit=12):
    target = _date(on_date)
    limit = max(1, min(int(limit), 50))
    rows = conn.execute(
        "SELECT i.*, p.play_count, p.last_played_at "
        "FROM item i LEFT JOIN item_play p ON p.item_id = i.id "
        "WHERE i.status = 'done' AND i.offloaded = 0 AND i.archive_missing = 0 "
        "ORDER BY i.favorite_order DESC, i.id DESC"
    ).fetchall()
    entries = []
    for row in rows:
        favorite_date = _parse_favorite_date(row["favorited_at"])
        if favorite_date is not None:
            entries.append((row, favorite_date))

    anniversary = [
        row for row, favorite_date in entries
        if favorite_date.month == target.month
        and favorite_date.day == target.day
        and favorite_date.year < target.year
    ]
    anniversary.sort(
        key=lambda row: (_parse_favorite_date(row["favorited_at"]), row["id"]),
        reverse=True,
    )
    anniversary_ids = [row["id"] for row in anniversary[:limit]]

    forgotten = sorted(
        (row for row in rows if row["id"] not in anniversary_ids),
        key=lambda row: (
            row["last_played_at"] is not None,
            row["last_played_at"] or "",
            -(row["favorite_order"] or row["id"]),
            -row["id"],
        ),
    )
    forgotten_ids = [row["id"] for row in forgotten[:limit]]

    used = set(anniversary_ids)
    era = [
        row for row, favorite_date in entries
        if favorite_date.month == target.month
        and favorite_date.year < target.year
        and row["id"] not in used
    ]
    era.sort(
        key=lambda row: (_parse_favorite_date(row["favorited_at"]), row["id"]),
        reverse=True,
    )
    era_ids = [row["id"] for row in era[:limit]]
    month_name = target.strftime("%B")

    sections = [
        {
            "key": "on_this_day",
            "title": "On this day",
            "description": f"Favorites saved on {month_name} {target.day} in earlier years.",
            "item_ids": anniversary_ids,
        },
        {
            "key": "forgotten",
            "title": "Worth another look",
            "description": "Local favorites you have never played here, or have not played lately.",
            "item_ids": forgotten_ids,
        },
        {
            "key": "era",
            "title": f"Your {month_name} archives",
            "description": f"More favorites from {month_name}s past.",
            "item_ids": era_ids,
        },
    ]
    return {"date": target.isoformat(), "sections": sections}
