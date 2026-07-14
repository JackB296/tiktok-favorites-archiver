"""Public Favorite projection for the Archive web interface.

The module hides SQLite rows and archive-file layout behind ``page`` and
``get``. Routes receive only the public Favorite shape consumed by the web app.
"""
import os

from core import store


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

_GALLERY_PRESET_FIELDS = {
    "search", "kind", "status", "order", "minDuration", "maxDuration",
    "minSize", "maxSize", "minWidth", "maxWidth", "minHeight", "maxHeight", "codec",
    "dateFrom", "dateTo", "orientation", "assets", "offloaded", "indexState", "include", "exclude",
    "minAttempts", "maxAttempts", "recovery",
}


def gallery_preset_filters(value):
    """Validate and normalize a saved Gallery filter snapshot."""
    if not isinstance(value, dict):
        raise ValueError("filters must be an object")
    if any(
        key not in _GALLERY_PRESET_FIELDS
        or (key == "recovery" and not isinstance(item, bool))
        or (key != "recovery" and not isinstance(item, str))
        for key, item in value.items()
    ):
        raise ValueError("filters contain an unsupported value")
    return {key: item for key, item in value.items() if item}


def _csv(value):
    return [term.strip() for term in value.split(",") if term.strip()]


def _single(value):
    return [value] if value else None


def _boolean(value):
    normalized = value.lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise ValueError("not a boolean")


# HTTP query param -> (page_items kwarg, parser). One row per filter:
# adding a Gallery filter = one entry here + one clause in
# store._page_filter_clauses (plus its store.PAGE_QUERY_DEFAULTS entry) + the
# frontend control. Adding a sort order = one store._PAGE_ORDERS entry —
# store.SELECTABLE_ORDERS and the route pick it up automatically.
_PAGE_PARAMS = {
    "search": ("query", str),
    "kind": ("kinds", _single),
    "status": ("statuses", _single),
    "limit": ("limit", int),
    "cursor": ("cursor", int),
    "order": ("order", str),
    "seed": ("seed", int),
    "min_duration": ("min_duration", float),
    "max_duration": ("max_duration", float),
    "min_size": ("min_size", int),
    "max_size": ("max_size", int),
    "min_width": ("min_width", int),
    "max_width": ("max_width", int),
    "min_height": ("min_height", int),
    "max_height": ("max_height", int),
    "min_attempts": ("min_attempts", int),
    "max_attempts": ("max_attempts", int),
    "codec": ("codecs", _csv),
    "orientation": ("orientations", _csv),
    "include": ("include", _csv),
    "exclude": ("exclude", _csv),
    "date_from": ("date_from", str),
    "date_to": ("date_to", str),
    "assets": ("has_assets", {"with": True, "without": False}.__getitem__),
    "audio": ("has_audio", {"with": True, "without": False}.__getitem__),
    "index_state": ("index_state", str),
    "recovery": ("recovery", _boolean),
    "offloaded": ("offloaded", {"with": True, "without": False}.__getitem__),
    "feed": ("feed", _boolean),
}


def parse_page_query(params):
    """HTTP query params -> store.page_items kwargs. ValueError on bad input."""
    query = {}
    for name, raw in params.items():
        if name not in _PAGE_PARAMS:
            raise ValueError(f"unknown query parameter: {name}")
        target, parse = _PAGE_PARAMS[name]
        try:
            query[target] = parse(raw)
        except (ValueError, KeyError):
            raise ValueError(f"invalid value for {name}: {raw!r}")
    if query.get("index_state") not in (None, "indexed", "missing", "failed"):
        raise ValueError("unknown index state")
    if query.get("order", "latest") not in store.SELECTABLE_ORDERS:
        raise ValueError("unknown item order")
    if query.get("order") == "random" and query.get("seed") is None:
        raise ValueError("random order requires a shuffle seed")
    return query


_MARK_ACTIONS = ("offload", "unoffload", "ignore", "unignore")


def parse_mark_request(body):
    """Validate POST /items/mark JSON. Returns (action, selector_kind, value, dry_run)."""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    action = body.get("action")
    if action not in _MARK_ACTIONS:
        raise ValueError("action must be one of: " + ", ".join(_MARK_ACTIONS))
    dry_run = body.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be a boolean")
    selectors = [k for k in ("ids", "range", "filter") if k in body]
    if len(selectors) != 1:
        raise ValueError("provide exactly one of: ids, range, filter")
    kind = selectors[0]
    value = body[kind]
    if kind == "ids":
        if (not isinstance(value, list) or not 1 <= len(value) <= 100
                or any(type(i) is not int or i < 1 for i in value)):
            raise ValueError("ids must contain 1 to 100 positive integer item IDs")
    elif kind == "range":
        if (not isinstance(value, dict)
                or type(value.get("first_id")) is not int or type(value.get("last_id")) is not int
                or not 1 <= value["first_id"] <= value["last_id"]):
            raise ValueError("range needs integer first_id <= last_id, both >= 1")
    else:
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise ValueError("filter must be an object of string query parameters")
        parsed = parse_page_query(value)   # reuses the Gallery vocabulary + errors
        for key in ("limit", "cursor", "order", "seed"):
            if key in parsed:
                raise ValueError(f"{key} is not a filter")
        value = parsed
    return action, kind, value, dry_run


class ArchiveItems:
    """Project Archive items into the web-facing Favorite representation."""

    def __init__(self, conn, download_dir):
        self._conn = conn
        self._download_dir = download_dir

    def get(self, item_id):
        row = store.get_item(self._conn, item_id)
        return None if row is None else self._public(row)

    def page(self, **query):
        query["limit"] = max(1, min(int(query.get("limit", 50)), 100))  # match the store's clamp, or next_cursor lies
        rows = store.page_items(self._conn, **query)
        items = [self._public(row) for row in rows]
        return {"items": items, "next_cursor": items[-1]["id"] if len(items) == query["limit"] else None}

    def window(self, item_id, limit=50):
        return {"items": [self._public(row) for row in store.window_items(self._conn, item_id, limit)]}

    def selected(self, item_ids):
        rows = [store.get_item(self._conn, item_id) for item_id in item_ids]
        return [self._public(row) for row in rows if row is not None]

    def _public(self, row):
        item_id = row["id"]
        data = {
            "id": item_id,
            "link": row["link"],
            "caption": row["caption"],
            "author": row["author"],
            "kind": row["kind"],
            "status": row["status"],
            "error": row["error"],
            "attempt_count": row["attempt_count"],
            "last_attempt_at": row["last_attempt_at"],
            "archive_missing": bool(row["archive_missing"]),
            "offloaded": bool(row["offloaded"]),
            "favorited_at": row["favorited_at"],
            "has_assets": bool(row["has_assets"]),
            "duration_s": row["duration_s"],
            "media_width": row["media_width"],
            "media_height": row["media_height"],
            "media_codec": row["media_codec"],
            "media_size": row["media_size"],
            "has_audio": None if row["has_audio"] is None else bool(row["has_audio"]),
            "audio_silent": None if row["audio_silent"] is None else bool(row["audio_silent"]),
            "song": None,
            "song_status": row["song_status"],
            "song_source": row["song_source"],
            "video_url": None,
            "images": [],
            "audio": None,
            "thumbnail_url": None,
        }
        if os.path.exists(os.path.join(self._download_dir, f"{item_id}.mp4")):
            version = f"?v={row['media_fingerprint']}" if row["media_fingerprint"] else ""
            data["video_url"] = f"/media/{item_id}.mp4{version}"
        if row["has_assets"]:
            data.update(self._slideshow_assets(item_id))
        thumbnail_path = row["custom_thumbnail_path"] or row["thumbnail_path"]
        if thumbnail_path:
            data["thumbnail_url"] = f"/media/{thumbnail_path}"
        if row["song_id"]:
            song = store.get_song(self._conn, row["song_id"])
            if song is not None:
                data["song"] = {
                    "title": song["title"],
                    "artist": song["artist"],
                    "album": song["album"],
                    "art_url": song["art_url"],
                    "shazam_url": song["shazam_url"],
                    "apple_url": song["apple_url"],
                    "spotify_url": song["spotify_url"],
                }
        return data

    def _slideshow_assets(self, item_id):
        folder = os.path.join(self._download_dir, str(item_id))
        if not os.path.isdir(folder):
            return {"images": [], "audio": None}
        names = sorted(os.listdir(folder))
        return {
            "images": [
                f"/media/{item_id}/{name}"
                for name in names
                if name.lower().endswith(_IMAGE_EXTS)
            ],
            "audio": f"/media/{item_id}/audio.mp3" if "audio.mp3" in names else None,
        }
