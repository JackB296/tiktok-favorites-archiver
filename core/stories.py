"""Validated, non-destructive Story Builder persistence."""
from datetime import datetime
import json
import math
import sqlite3

from core import store


class StoryError(ValueError):
    pass


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _text(value, field, *, required=False, limit=500):
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise StoryError(f"{field} must be text")
    cleaned = value.strip()
    if required and not cleaned:
        raise StoryError(f"{field} is required")
    if len(cleaned) > limit:
        raise StoryError(f"{field} must be at most {limit} characters")
    return cleaned


def _seconds(value, field, *, default=None):
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StoryError(f"{field} must be a number")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise StoryError(f"{field} must be a non-negative finite number")
    return value


def _chapters(conn, value):
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise StoryError("chapters must contain 1 to 100 entries")
    result = []
    seen = set()
    for index, chapter in enumerate(value, start=1):
        if not isinstance(chapter, dict):
            raise StoryError(f"chapter {index} must be an object")
        if any(
            field not in {"item_id", "title", "start_s", "end_s"}
            for field in chapter
        ):
            raise StoryError(f"chapter {index} contains an unsupported field")
        item_id = chapter.get("item_id")
        if type(item_id) is not int or item_id < 1:
            raise StoryError(f"chapter {index} item_id must be a positive integer")
        if item_id in seen:
            raise StoryError("each favorite can appear only once in a story")
        item = store.get_item(conn, item_id)
        if item is None:
            raise StoryError(f"favorite #{item_id} was not found")
        seen.add(item_id)
        title = chapter.get("title")
        if title is None or (isinstance(title, str) and not title.strip()):
            title = f"Favorite #{item_id}"
        title = _text(title, f"chapter {index} title", required=True, limit=120)
        start = _seconds(chapter.get("start_s"), f"chapter {index} start_s", default=0.0)
        end = _seconds(chapter.get("end_s"), f"chapter {index} end_s")
        if end is not None and end <= start:
            raise StoryError(f"chapter {index} end_s must be greater than start_s")
        duration = item["duration_s"]
        if duration is not None:
            duration = float(duration)
            if start >= duration:
                raise StoryError(f"chapter {index} starts after the favorite ends")
            if end is not None and end > duration + 0.01:
                raise StoryError(f"chapter {index} ends after the favorite ends")
        result.append({
            "item_id": item_id,
            "title": title,
            "start_s": start,
            "end_s": end,
        })
    return result


def _public(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "chapters": json.loads(row["chapters_json"]),
        "rendered_path": row["rendered_path"],
        "rendered_at": row["rendered_at"],
        "render_error": row["render_error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_stories(conn, limit=200):
    limit = max(1, min(int(limit), 500))
    return [
        _public(row) for row in conn.execute(
            "SELECT * FROM story ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    ]


def get_story(conn, story_id):
    row = conn.execute(
        "SELECT * FROM story WHERE id = ?", (int(story_id),),
    ).fetchone()
    return None if row is None else _public(row)


def create_story(conn, body):
    if not isinstance(body, dict):
        raise StoryError("story must be an object")
    if any(field not in {"name", "description", "chapters"} for field in body):
        raise StoryError("story contains an unsupported field")
    name = _text(body.get("name"), "name", required=True, limit=80)
    description = _text(body.get("description"), "description", limit=500)
    chapters = _chapters(conn, body.get("chapters"))
    now = _now()
    try:
        cursor = conn.execute(
            "INSERT INTO story "
            "(name, description, chapters_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, description, json.dumps(chapters, separators=(",", ":")), now, now),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise StoryError("a story with that name already exists") from exc
    return get_story(conn, cursor.lastrowid)


def update_story(conn, story_id, body):
    current = get_story(conn, story_id)
    if current is None:
        return None
    if not isinstance(body, dict):
        raise StoryError("story must be an object")
    allowed = {"name", "description", "chapters"}
    if not body or any(field not in allowed for field in body):
        raise StoryError("update must include name, description, or chapters")
    name = _text(body.get("name", current["name"]), "name", required=True, limit=80)
    description = _text(
        body.get("description", current["description"]), "description", limit=500,
    )
    chapters = _chapters(conn, body.get("chapters", current["chapters"]))
    chapters_changed = chapters != current["chapters"]
    try:
        if chapters_changed:
            conn.execute(
                "UPDATE story SET name = ?, description = ?, chapters_json = ?, "
                "render_error = NULL, updated_at = ? "
                "WHERE id = ?",
                (
                    name,
                    description,
                    json.dumps(chapters, separators=(",", ":")),
                    _now(),
                    int(story_id),
                ),
            )
        else:
            conn.execute(
                "UPDATE story SET name = ?, description = ?, chapters_json = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    name,
                    description,
                    json.dumps(chapters, separators=(",", ":")),
                    _now(),
                    int(story_id),
                ),
            )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise StoryError("a story with that name already exists") from exc
    return get_story(conn, story_id)


def delete_story(conn, story_id):
    cursor = conn.execute("DELETE FROM story WHERE id = ?", (int(story_id),))
    conn.commit()
    return cursor.rowcount > 0


def record_render_success(conn, story_id, rendered_path):
    conn.execute(
        "UPDATE story SET rendered_path = ?, rendered_at = ?, render_error = NULL, "
        "updated_at = ? WHERE id = ?",
        (rendered_path, _now(), _now(), int(story_id)),
    )
    conn.commit()
    return get_story(conn, story_id)


def record_render_error(conn, story_id, error):
    conn.execute(
        "UPDATE story SET render_error = ?, updated_at = ? WHERE id = ?",
        (str(error)[:1000], _now(), int(story_id)),
    )
    conn.commit()
    return get_story(conn, story_id)
