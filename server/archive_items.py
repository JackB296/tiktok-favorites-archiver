"""Public Favorite projection for the Archive web interface.

The module hides SQLite rows and archive-file layout behind ``page`` and
``get``. Routes receive only the public Favorite shape consumed by the web app.
"""
import os

from core import discovery, layout, selection, store

_GALLERY_PRESET_FIELDS = {
    "search", "kind", "status", "order", "minDuration", "maxDuration",
    "minSize", "maxSize", "minWidth", "maxWidth", "minHeight", "maxHeight", "codec",
    "dateFrom", "dateTo", "orientation", "assets", "audio", "offloaded", "indexState", "include", "exclude",
    "minAttempts", "maxAttempts", "recovery",
    "creator", "hashtag",
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


_PRESET_TO_PAGE = {
    "search": ("search", lambda value: value),
    "kind": ("kind", lambda value: value),
    "status": ("status", lambda value: value),
    "order": ("order", lambda value: value),
    "minDuration": ("min_duration", lambda value: value),
    "maxDuration": ("max_duration", lambda value: value),
    "minSize": ("min_size", lambda value: str(round(float(value) * 1024 * 1024))),
    "maxSize": ("max_size", lambda value: str(round(float(value) * 1024 * 1024))),
    "minWidth": ("min_width", lambda value: value),
    "maxWidth": ("max_width", lambda value: value),
    "minHeight": ("min_height", lambda value: value),
    "maxHeight": ("max_height", lambda value: value),
    "minAttempts": ("min_attempts", lambda value: value),
    "maxAttempts": ("max_attempts", lambda value: value),
    "recovery": ("recovery", lambda value: "true" if value else ""),
    "codec": ("codec", lambda value: value),
    "dateFrom": ("date_from", lambda value: value),
    "dateTo": ("date_to", lambda value: f"{value}T23:59:59"),
    "orientation": ("orientation", lambda value: value),
    "assets": ("assets", lambda value: value),
    "audio": ("audio", lambda value: value),
    "offloaded": ("offloaded", lambda value: value),
    "indexState": ("index_state", lambda value: value),
    "include": ("include", lambda value: value),
    "exclude": ("exclude", lambda value: value),
    "creator": ("creator", lambda value: value),
    "hashtag": ("hashtag", lambda value: value),
}


def gallery_preset_query(filters, *, seed=None):
    """Translate the persisted camelCase Gallery snapshot to page kwargs."""
    params = {}
    for key, value in gallery_preset_filters(filters).items():
        if key not in _PRESET_TO_PAGE:
            continue
        wire, convert = _PRESET_TO_PAGE[key]
        converted = convert(value)
        if converted != "":
            params[wire] = str(converted)
    if params.get("order") == "random":
        params["seed"] = str(seed if seed is not None else 0)
    return parse_page_query(params)


# --- saved named-list request bodies -----------------------------------------
# One parser per collection the web app can save. ``parse_saved_list`` returns
# (name, payload) ready for ``store.save_saved_list``; the payload keys double
# as the create-response fields, so wire shapes stay per-collection.

def _valid_name(body, noun):
    if not isinstance(body, dict):
        raise ValueError(f"{noun} must be an object")
    name = body.get("name")
    if not isinstance(name, str) or not (name := name.strip()) or len(name) > 80:
        raise ValueError("name must be between 1 and 80 characters")
    return name


def _unique_positive_ids(values, field, limit):
    if (
        not isinstance(values, list)
        or not 1 <= len(values) <= limit
        or len(set(values)) != len(values)
        or any(type(value) is not int or value < 1 for value in values)
    ):
        raise ValueError(f"{field} must contain 1 to {limit} unique positive integer IDs")
    return values


def _preset_body(body):
    return {"filters": gallery_preset_filters(body.get("filters"))}


def _term_list_body(body):
    mode = body.get("mode")
    terms = body.get("terms")
    if mode not in ("include", "exclude"):
        raise ValueError("mode must be include or exclude")
    if not isinstance(terms, list) or not 1 <= len(terms) <= 100:
        raise ValueError("terms must contain 1 to 100 entries")
    cleaned = []
    for term in terms:
        if not isinstance(term, str):
            raise ValueError("each term must be 1 to 100 characters")
        term = term.strip()
        if not term or len(term) > 100:
            raise ValueError("each term must be 1 to 100 characters")
        if term not in cleaned:
            cleaned.append(term)
    return {"mode": mode, "terms": cleaned}


def _queue_body(body):
    return {"item_ids": _unique_positive_ids(body.get("item_ids"), "item_ids", 100)}


def _playlist_body(body):
    return {"song_ids": _unique_positive_ids(body.get("song_ids"), "song_ids", 1000)}


# resource path -> (store kind, body noun, display noun, payload parser)
SAVED_LIST_RESOURCES = {
    "gallery-presets": ("gallery_preset", "preset", "preset", _preset_body),
    "gallery-term-lists": ("gallery_term_list", "list", "term list", _term_list_body),
    "playback-queues": ("playback_queue", "queue", "playback queue", _queue_body),
    "song-playlists": ("song_playlist", "playlist", "playlist", _playlist_body),
}


_SONG_MATCH_FIELDS = ("key", "artist", "album", "art_url", "shazam_url", "apple_url", "spotify_url")


def parse_song_match(body):
    """Validate a manual song-attach body -> field dict for ``songid.SongMatch``.

    Every field must be a string (or absent); a non-string title once reached
    ``dedup_key``'s ``.strip()`` and 500'd, and non-string metadata reached
    sqlite as un-bindable values.
    """
    if not isinstance(body, dict):
        raise ValueError("song must be an object")
    title = body.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("a song title is required")
    fields = {"title": title}
    for field in _SONG_MATCH_FIELDS:
        value = body.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        fields[field] = value
    return fields


def parse_saved_list(resource, body):
    """Validate one saved-list create body -> ``(name, payload)``. ValueError on bad input."""
    _kind, body_noun, _display_noun, parse_payload = SAVED_LIST_RESOURCES[resource]
    name = _valid_name(body, body_noun)
    return name, parse_payload(body)


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
    "creator": ("creator_key", discovery.normalize_creator),
    "hashtag": ("hashtag_key", discovery.normalize_hashtag),
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
        rows = selection.ArchiveSelection.gallery(query, scope="page").rows(self._conn)
        items = self._public_batch(rows)
        return {"items": items, "next_cursor": items[-1]["id"] if len(items) == query["limit"] else None}

    def window(self, item_id, limit=50):
        return {"items": self._public_batch(store.window_items(self._conn, item_id, limit))}

    def selected(self, item_ids):
        by_id = store.get_items(self._conn, item_ids)
        rows = [by_id[item_id] for item_id in item_ids if item_id in by_id]
        return self._public_batch(rows)

    def _public_batch(self, rows):
        """Project many rows with one directory listing and one song query
        instead of a per-row ``os.path.exists`` and ``get_song`` (N+1)."""
        files = os.listdir(self._download_dir) if os.path.isdir(self._download_dir) else []
        movies = set(layout.finished_movie_ids(files))
        songs = store.get_songs(self._conn, [row["song_id"] for row in rows if row["song_id"]])
        identities = discovery.identities_for_items(
            self._conn, [row["id"] for row in rows],
        )
        return [
            self._public(row, movies=movies, songs=songs, identities=identities)
            for row in rows
        ]

    def _public(self, row, movies=None, songs=None, identities=None):
        item_id = row["id"]
        identity = (
            identities.get(item_id, {"creator": None, "hashtags": []})
            if identities is not None
            else discovery.identities_for_items(self._conn, [item_id]).get(
                item_id, {"creator": None, "hashtags": []},
            )
        )
        data = {
            "id": item_id,
            "link": row["link"],
            "caption": row["caption"],
            "author": row["author"],
            "creator": identity["creator"],
            "hashtags": identity["hashtags"],
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
        movie_present = (
            item_id in movies if movies is not None
            else os.path.exists(layout.movie(self._download_dir, item_id))
        )
        if movie_present:
            version = f"?v={row['media_fingerprint']}" if row["media_fingerprint"] else ""
            data["video_url"] = f"/media/{item_id}.mp4{version}"
        if row["has_assets"]:
            data.update(self._slideshow_assets(item_id))
        thumbnail_path = row["custom_thumbnail_path"] or row["thumbnail_path"]
        if thumbnail_path:
            data["thumbnail_url"] = f"/media/{thumbnail_path}"
        if row["song_id"]:
            song = songs.get(row["song_id"]) if songs is not None else store.get_song(self._conn, row["song_id"])
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
        images = layout.slideshow_images(self._download_dir, item_id)
        if not images and not os.path.isdir(layout.assets_dir(self._download_dir, item_id)):
            return {"images": [], "audio": None}
        return {
            "images": [f"/media/{item_id}/{name}" for name in images],
            "audio": f"/media/{item_id}/audio.mp3"
            if os.path.isfile(layout.slideshow_audio(self._download_dir, item_id)) else None,
        }
