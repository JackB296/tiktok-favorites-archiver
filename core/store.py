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

from core import migrations, search_query as structured_search

# Lifecycle vocabularies — kept as data (not DB-enforced) so they can evolve.
ITEM_STATUSES = ("pending", "resolving", "downloading", "done", "failed", "skipped", "ignored", "expired")
ITEM_KINDS = ("unknown", "video", "slideshow", "unresolved")
RUN_STATES = ("idle", "running", "paused", "stopping", "stopped", "failed")

DEFAULT_CONCURRENCY = 4

_ITEM_SEARCH_COLUMNS = (
    "caption", "author", "link", "description", "creator_username", "search_song_text",
)
_ITEM_SEARCH_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS item_search USING fts5(
    caption,
    author,
    link,
    description,
    creator_username,
    search_song_text,
    content='item',
    content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS item_search_insert AFTER INSERT ON item BEGIN
    INSERT INTO item_search(
        rowid, caption, author, link, description, creator_username, search_song_text
    ) VALUES (
        new.id, new.caption, new.author, new.link, new.description,
        new.creator_username, new.search_song_text
    );
END;
CREATE TRIGGER IF NOT EXISTS item_search_delete AFTER DELETE ON item BEGIN
    INSERT INTO item_search(
        item_search, rowid, caption, author, link, description,
        creator_username, search_song_text
    ) VALUES (
        'delete', old.id, old.caption, old.author, old.link, old.description,
        old.creator_username, old.search_song_text
    );
END;
CREATE TRIGGER IF NOT EXISTS item_search_update AFTER UPDATE OF
caption, author, link, description, creator_username, search_song_text ON item BEGIN
    INSERT INTO item_search(
        item_search, rowid, caption, author, link, description,
        creator_username, search_song_text
    ) VALUES (
        'delete', old.id, old.caption, old.author, old.link, old.description,
        old.creator_username, old.search_song_text
    );
    INSERT INTO item_search(
        rowid, caption, author, link, description, creator_username, search_song_text
    ) VALUES (
        new.id, new.caption, new.author, new.link, new.description,
        new.creator_username, new.search_song_text
    );
END;
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS item (
    id           INTEGER PRIMARY KEY,   -- == <n> in downloads/<n>.mp4
    favorite_order INTEGER,             -- chronological export position; independent of filename
    link         TEXT NOT NULL UNIQUE,
    favorited_at TEXT,
    kind         TEXT NOT NULL DEFAULT 'unknown',
    status       TEXT NOT NULL DEFAULT 'pending',
    has_assets   INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    caption      TEXT,
    author       TEXT,
    description  TEXT,
    source_posted_at TEXT,
    creator_username TEXT,
    creator_external_id TEXT,
    creator_url TEXT,
    source_duration_s REAL,
    source_width INTEGER,
    source_height INTEGER,
    view_count INTEGER,
    like_count INTEGER,
    comment_count INTEGER,
    repost_count INTEGER,
    save_count INTEGER,
    source_thumbnail_path TEXT,
    source_info_status TEXT,
    source_info_at TEXT,
    source_info_error TEXT,
    comments_status TEXT,
    download_source TEXT,
    portable_metadata_status TEXT,
    portable_metadata_hash TEXT,
    portable_metadata_at TEXT,
    portable_metadata_error TEXT,
    enrich_status TEXT,                  -- NULL=never tried, 'ok'=got metadata, 'unavailable'=tried, none returned
    thumbnail_path TEXT,
    custom_thumbnail_path TEXT,
    duration_s    REAL,
    media_width   INTEGER,
    media_height  INTEGER,
    media_codec   TEXT,
    media_size    INTEGER,
    has_audio     INTEGER,
    audio_silent  INTEGER,
    media_fingerprint TEXT,
    indexed_at    TEXT,
    index_error   TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    archive_missing INTEGER NOT NULL DEFAULT 0,
    offloaded    INTEGER NOT NULL DEFAULT 0,
    song_id       INTEGER,               -- references song(id); NULL = no identified song
    song_status   TEXT,                  -- NULL=never tried, 'identified'/'no_match'/'error'
    song_source   TEXT,                  -- 'auto' (Shazam) or 'manual' (user match)
    song_identified_at TEXT,
    song_error    TEXT,
    search_song_text TEXT,
    creator_id    INTEGER,
    creator_analyze_requested INTEGER NOT NULL DEFAULT 0,
    creator_identify_requested INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_item_status ON item(status);
CREATE INDEX IF NOT EXISTS idx_item_media_size    ON item(media_size, id)      WHERE media_size IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_item_duration      ON item(duration_s, id)      WHERE duration_s IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_item_favorited_at  ON item(favorited_at, id)    WHERE favorited_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_item_source_posted ON item(source_posted_at, id) WHERE source_posted_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_item_views         ON item(view_count, id)       WHERE view_count IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_item_likes         ON item(like_count, id)       WHERE like_count IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_item_comments      ON item(comment_count, id)    WHERE comment_count IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_item_attempts      ON item(attempt_count, id);
CREATE INDEX IF NOT EXISTS idx_item_last_attempt  ON item(last_attempt_at, id) WHERE last_attempt_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_item_author        ON item(author, id)          WHERE author IS NOT NULL;

CREATE TABLE IF NOT EXISTS comment_snapshot (
    id             INTEGER PRIMARY KEY,
    item_id        INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    captured_at    TEXT NOT NULL,
    comments_json  TEXT NOT NULL,
    saved_count    INTEGER NOT NULL,
    reported_count INTEGER,
    added_count    INTEGER NOT NULL,
    removed_count  INTEGER NOT NULL,
    changed_count  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comment_snapshot_item
    ON comment_snapshot(item_id, id DESC);

-- One row per distinct identified track. Many favorites share one sound, so
-- songs are stored once (deduped by dedup_key) and referenced by item.song_id.
CREATE TABLE IF NOT EXISTS song (
    id          INTEGER PRIMARY KEY,
    dedup_key   TEXT NOT NULL UNIQUE,   -- 'shazam:<key>' when known, else 'ta:<title>|<artist>'
    shazam_key  TEXT,                   -- Shazam's stable track id, when available
    title       TEXT NOT NULL,
    artist      TEXT,
    album       TEXT,
    art_url     TEXT,                   -- cover art
    shazam_url  TEXT,                   -- canonical Shazam track page
    apple_url   TEXT,                   -- direct Apple Music link, if Shazam returned one
    spotify_url TEXT,                   -- direct Spotify link, if Shazam returned one
    created_at  TEXT NOT NULL
);

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
    song_id_enabled INTEGER NOT NULL DEFAULT 0,   -- opt-in; sends audio to Shazam
    portable_metadata_enabled INTEGER NOT NULL DEFAULT 0,
    default_audio_name TEXT,                       -- custom slideshow fallback filename; NULL = bundled default.mp3
    local_analysis_pipeline_migrated INTEGER NOT NULL DEFAULT 1,
    source_metadata_pipeline_migrated INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gallery_preset (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    filters_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gallery_term_list (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL CHECK (mode IN ('include', 'exclude')),
    terms_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS playback_queue (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    item_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spotify_auth (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    client_id     TEXT,                  -- the owner's own Spotify app (PKCE, no secret)
    access_token  TEXT,
    refresh_token TEXT,
    expires_at    INTEGER,               -- unix seconds
    account_name  TEXT,                  -- display name shown in the Music tab
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS song_playlist (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    song_ids_json TEXT NOT NULL,   -- references song(id)
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_history (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    pipeline_id TEXT,
    parent_kind TEXT,
    phase TEXT,
    phase_index INTEGER,
    outcome TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    counts_json TEXT,
    retry_of INTEGER,
    params_json TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS pipeline_setting (
    kind TEXT PRIMARY KEY,
    phases_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_schedule (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    run_kind TEXT NOT NULL,
    cadence TEXT NOT NULL CHECK (cadence IN ('daily', 'weekly')),
    local_time TEXT NOT NULL,
    weekday INTEGER,
    timezone TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    next_due_at TEXT,
    last_local_date TEXT,
    last_started_at TEXT,
    last_outcome TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS creator (
    id INTEGER PRIMARY KEY,
    canonical_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS creator_monitor (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    interval_hours INTEGER NOT NULL DEFAULT 6,
    next_check_at TEXT,
    last_checked_at TEXT,
    last_new_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    archive_mode TEXT NOT NULL DEFAULT 'all',
    keywords_json TEXT NOT NULL DEFAULT '[]',
    exclude_reposts INTEGER NOT NULL DEFAULT 0,
    max_backlog_days INTEGER,
    collect_comments INTEGER NOT NULL DEFAULT 1,
    analyze_new INTEGER NOT NULL DEFAULT 0,
    identify_songs INTEGER NOT NULL DEFAULT 0,
    last_seen_post_ids_json TEXT NOT NULL DEFAULT '[]',
    last_changed_count INTEGER NOT NULL DEFAULT 0,
    last_missing_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_creator_monitor_due
    ON creator_monitor(enabled, next_check_at);
CREATE TABLE IF NOT EXISTS source_health_sample (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    attempted INTEGER NOT NULL,
    succeeded INTEGER NOT NULL,
    empty_count INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    details_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_health_sample_source
    ON source_health_sample(source, id DESC);
CREATE TABLE IF NOT EXISTS hashtag (
    id INTEGER PRIMARY KEY,
    canonical_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_hashtag (
    item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    hashtag_id INTEGER NOT NULL REFERENCES hashtag(id) ON DELETE CASCADE,
    PRIMARY KEY(item_id, hashtag_id)
);
CREATE INDEX IF NOT EXISTS idx_item_creator ON item(creator_id);
CREATE INDEX IF NOT EXISTS idx_item_hashtag_tag ON item_hashtag(hashtag_id, item_id);
CREATE TABLE IF NOT EXISTS storage_location (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL UNIQUE,
    available INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_checked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_placement (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    location_id INTEGER NOT NULL REFERENCES storage_location(id) ON DELETE RESTRICT,
    relative_root TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    byte_count INTEGER NOT NULL DEFAULT 0,
    manifest_digest TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    verified_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(item_id, location_id)
);
CREATE INDEX IF NOT EXISTS idx_media_placement_location ON media_placement(location_id);
CREATE TABLE IF NOT EXISTS media_placement_file (
    placement_id INTEGER NOT NULL REFERENCES media_placement(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    byte_count INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    PRIMARY KEY(placement_id, path)
);
CREATE TABLE IF NOT EXISTS analysis_segment (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('transcript', 'ocr')),
    text TEXT NOT NULL,
    start_s REAL NOT NULL DEFAULT 0 CHECK (start_s >= 0),
    end_s REAL CHECK (end_s IS NULL OR end_s >= start_s),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analysis_segment_item ON analysis_segment(item_id, start_s, id);
CREATE TABLE IF NOT EXISTS analysis_source_state (
    item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('transcript', 'ocr')),
    origin TEXT NOT NULL CHECK (origin IN ('manual', 'generated')),
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    media_fingerprint TEXT,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT,
    attempted_at TEXT NOT NULL,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(item_id, source)
);
CREATE INDEX IF NOT EXISTS idx_analysis_source_status
ON analysis_source_state(status, source, item_id);
CREATE VIRTUAL TABLE IF NOT EXISTS analysis_search USING fts5(
    text,
    content='analysis_segment',
    content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS analysis_search_insert AFTER INSERT ON analysis_segment BEGIN
    INSERT INTO analysis_search(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS analysis_search_delete AFTER DELETE ON analysis_segment BEGIN
    INSERT INTO analysis_search(analysis_search, rowid, text)
    VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS analysis_search_update AFTER UPDATE OF text ON analysis_segment BEGIN
    INSERT INTO analysis_search(analysis_search, rowid, text)
    VALUES ('delete', old.id, old.text);
    INSERT INTO analysis_search(rowid, text) VALUES (new.id, new.text);
END;
CREATE TABLE IF NOT EXISTS item_play (
    item_id INTEGER PRIMARY KEY REFERENCES item(id) ON DELETE CASCADE,
    play_count INTEGER NOT NULL DEFAULT 0 CHECK (play_count >= 0),
    first_played_at TEXT NOT NULL,
    last_played_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_item_play_last ON item_play(last_played_at, item_id);
CREATE TABLE IF NOT EXISTS item_annotation (
    item_id INTEGER PRIMARY KEY REFERENCES item(id) ON DELETE CASCADE,
    starred INTEGER NOT NULL DEFAULT 0 CHECK (starred IN (0, 1)),
    note TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_item_annotation_starred
ON item_annotation(starred, item_id) WHERE starred = 1;
CREATE INDEX IF NOT EXISTS idx_item_annotation_reviewed
ON item_annotation(reviewed_at, item_id);
CREATE TABLE IF NOT EXISTS private_tag (
    id INTEGER PRIMARY KEY,
    canonical_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_private_tag (
    item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES private_tag(id) ON DELETE CASCADE,
    PRIMARY KEY(item_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_item_private_tag_tag
ON item_private_tag(tag_id, item_id);
CREATE TABLE IF NOT EXISTS media_digest (
    item_id INTEGER PRIMARY KEY REFERENCES item(id) ON DELETE CASCADE,
    media_fingerprint TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
    hashed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_digest_sha256
ON media_digest(sha256, item_id);
CREATE TABLE IF NOT EXISTS archive_channel (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    preset_id INTEGER NOT NULL REFERENCES gallery_preset(id) ON DELETE CASCADE,
    shuffle INTEGER NOT NULL DEFAULT 0 CHECK (shuffle IN (0, 1)),
    prefer_unwatched INTEGER NOT NULL DEFAULT 1 CHECK (prefer_unwatched IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_archive_channel_preset
ON archive_channel(preset_id, id);
CREATE TABLE IF NOT EXISTS import_history (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    selection TEXT NOT NULL DEFAULT 'favorites',
    digest TEXT NOT NULL,
    favorite_count INTEGER NOT NULL CHECK (favorite_count >= 0),
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_import_history_time ON import_history(imported_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_import_history_selection ON import_history(selection, id DESC);
CREATE TABLE IF NOT EXISTS import_membership (
    import_id INTEGER NOT NULL REFERENCES import_history(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE RESTRICT,
    link TEXT NOT NULL,
    favorited_at TEXT,
    PRIMARY KEY(import_id, link)
);
CREATE INDEX IF NOT EXISTS idx_import_membership_item ON import_membership(item_id, import_id);
CREATE TABLE IF NOT EXISTS story (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    chapters_json TEXT NOT NULL,
    rendered_path TEXT,
    rendered_at TEXT,
    render_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_comment_search (
    item_id INTEGER PRIMARY KEY REFERENCES item(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES comment_snapshot(id) ON DELETE CASCADE,
    text TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS comment_search USING fts5(
    text,
    content='item_comment_search',
    content_rowid='item_id'
);
CREATE TRIGGER IF NOT EXISTS comment_search_insert AFTER INSERT ON item_comment_search BEGIN
    INSERT INTO comment_search(rowid, text) VALUES (new.item_id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS comment_search_delete AFTER DELETE ON item_comment_search BEGIN
    INSERT INTO comment_search(comment_search, rowid, text) VALUES ('delete', old.item_id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS comment_search_update AFTER UPDATE OF text ON item_comment_search BEGIN
    INSERT INTO comment_search(comment_search, rowid, text) VALUES ('delete', old.item_id, old.text);
    INSERT INTO comment_search(rowid, text) VALUES (new.item_id, new.text);
END;
CREATE TABLE IF NOT EXISTS comment_entry (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES comment_snapshot(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    comment_key TEXT NOT NULL,
    parent_key TEXT,
    author TEXT,
    author_username TEXT,
    text TEXT NOT NULL,
    posted_at INTEGER,
    like_count INTEGER,
    UNIQUE(snapshot_id, comment_key)
);
CREATE INDEX IF NOT EXISTS idx_comment_entry_snapshot ON comment_entry(snapshot_id, id);
CREATE INDEX IF NOT EXISTS idx_comment_entry_item ON comment_entry(item_id, snapshot_id, id);
CREATE VIRTUAL TABLE IF NOT EXISTS comment_entry_search USING fts5(
    text, author, author_username,
    content='comment_entry', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS comment_entry_search_insert AFTER INSERT ON comment_entry BEGIN
    INSERT INTO comment_entry_search(rowid, text, author, author_username)
    VALUES (new.id, new.text, new.author, new.author_username);
END;
CREATE TRIGGER IF NOT EXISTS comment_entry_search_delete AFTER DELETE ON comment_entry BEGIN
    INSERT INTO comment_entry_search(comment_entry_search, rowid, text, author, author_username)
    VALUES ('delete', old.id, old.text, old.author, old.author_username);
END;
CREATE TRIGGER IF NOT EXISTS comment_entry_search_update AFTER UPDATE OF text, author, author_username ON comment_entry BEGIN
    INSERT INTO comment_entry_search(comment_entry_search, rowid, text, author, author_username)
    VALUES ('delete', old.id, old.text, old.author, old.author_username);
    INSERT INTO comment_entry_search(rowid, text, author, author_username)
    VALUES (new.id, new.text, new.author, new.author_username);
END;
"""

_ITEM_MIGRATIONS = {
    "enrich_status": "TEXT",
    "favorite_order": "INTEGER",
    "thumbnail_path": "TEXT",
    "custom_thumbnail_path": "TEXT",
    "duration_s": "REAL",
    "media_width": "INTEGER",
    "media_height": "INTEGER",
    "media_codec": "TEXT",
    "media_size": "INTEGER",
    "has_audio": "INTEGER",
    "audio_silent": "INTEGER",
    "media_fingerprint": "TEXT",
    "indexed_at": "TEXT",
    "index_error": "TEXT",
    "attempt_count": "INTEGER NOT NULL DEFAULT 0",
    "last_attempt_at": "TEXT",
    "archive_missing": "INTEGER NOT NULL DEFAULT 0",
    "offloaded": "INTEGER NOT NULL DEFAULT 0",
    "song_id": "INTEGER",
    "song_status": "TEXT",
    "song_source": "TEXT",
    "song_identified_at": "TEXT",
    "song_error": "TEXT",
    "search_song_text": "TEXT",
    "creator_id": "INTEGER",
    "creator_analyze_requested": "INTEGER NOT NULL DEFAULT 0",
    "creator_identify_requested": "INTEGER NOT NULL DEFAULT 0",
    "description": "TEXT",
    "source_posted_at": "TEXT",
    "creator_username": "TEXT",
    "creator_external_id": "TEXT",
    "creator_url": "TEXT",
    "source_duration_s": "REAL",
    "source_width": "INTEGER",
    "source_height": "INTEGER",
    "view_count": "INTEGER",
    "like_count": "INTEGER",
    "comment_count": "INTEGER",
    "repost_count": "INTEGER",
    "save_count": "INTEGER",
    "source_thumbnail_path": "TEXT",
    "source_info_status": "TEXT",
    "source_info_at": "TEXT",
    "source_info_error": "TEXT",
    "comments_status": "TEXT",
    "download_source": "TEXT",
    "portable_metadata_status": "TEXT",
    "portable_metadata_hash": "TEXT",
    "portable_metadata_at": "TEXT",
    "portable_metadata_error": "TEXT",
}

_RUN_HISTORY_MIGRATIONS = {
    "pipeline_id": "TEXT",
    "parent_kind": "TEXT",
    "phase": "TEXT",
    "phase_index": "INTEGER",
    "retry_of": "INTEGER",
    "params_json": "TEXT",
    "error": "TEXT",
}

_IMPORT_HISTORY_MIGRATIONS = {
    "selection": "TEXT NOT NULL DEFAULT 'favorites'",
}


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _comment_search_text(comments):
    """Bounded full-text document for one latest local comment snapshot."""
    parts = []
    length = 0
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        for field in ("text", "author", "author_username"):
            value = comment.get(field)
            if not isinstance(value, str) or not (value := value.strip()):
                continue
            value = value[:4000]
            parts.append(value)
            length += len(value) + 1
            if length >= 2 * 1024 * 1024:
                return "\n".join(parts)[:2 * 1024 * 1024]
    return "\n".join(parts)


def _replace_comment_entries(conn, snapshot_id, item_id, comments):
    conn.execute("DELETE FROM comment_entry WHERE snapshot_id = ?", (snapshot_id,))
    for position, comment in enumerate(comments):
        if not isinstance(comment, dict):
            continue
        key = _comment_identity(comment)
        text = comment.get("text")
        if not isinstance(text, str):
            text = ""
        conn.execute(
            "INSERT INTO comment_entry "
            "(snapshot_id, item_id, comment_key, parent_key, author, author_username, "
            "text, posted_at, like_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot_id, item_id, key, str(comment.get("parent") or "") or None,
                str(comment.get("author") or "") or None,
                str(comment.get("author_username") or "") or None,
                text[:20000], comment.get("timestamp") if isinstance(comment.get("timestamp"), (int, float)) else None,
                comment.get("like_count") if isinstance(comment.get("like_count"), int) else None,
            ),
        )


def _ensure_item_search_schema(conn):
    """Upgrade the external-content FTS table when searchable fields grow."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'item_search'"
    ).fetchone()
    columns = tuple(
        row["name"] for row in conn.execute("PRAGMA table_info(item_search)")
    ) if exists else ()
    for trigger in ("item_search_insert", "item_search_delete", "item_search_update"):
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    changed = columns != _ITEM_SEARCH_COLUMNS
    if changed:
        conn.execute("DROP TABLE IF EXISTS item_search")
    conn.executescript(_ITEM_SEARCH_SCHEMA)
    # Populate a replacement external-content index before any later item
    # UPDATE fires its FTS delete trigger. Deleting terms from an empty FTS5
    # index is reported as "database disk image is malformed" by SQLite.
    if changed and conn.execute("SELECT 1 FROM item LIMIT 1").fetchone() is not None:
        conn.execute("INSERT INTO item_search(item_search) VALUES ('rebuild')")


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
    # Add missing item columns BEFORE the schema script: SCHEMA's indexes
    # reference the newest columns, and CREATE TABLE IF NOT EXISTS will not
    # touch an existing table — so an old database must be migrated first or
    # the index creation fails with "no such column".
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'item'").fetchone():
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(item)")}
        for name, type_name in _ITEM_MIGRATIONS.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE item ADD COLUMN {name} {type_name}")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'import_history'").fetchone():
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(import_history)")}
        for name, type_name in _IMPORT_HISTORY_MIGRATIONS.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE import_history ADD COLUMN {name} {type_name}")
    conn.executescript(SCHEMA)
    monitor_columns = {row["name"] for row in conn.execute("PRAGMA table_info(creator_monitor)")}
    monitor_migrations = {
        "archive_mode": "TEXT NOT NULL DEFAULT 'all'",
        "keywords_json": "TEXT NOT NULL DEFAULT '[]'",
        "exclude_reposts": "INTEGER NOT NULL DEFAULT 0",
        "max_backlog_days": "INTEGER",
        "collect_comments": "INTEGER NOT NULL DEFAULT 1",
        "analyze_new": "INTEGER NOT NULL DEFAULT 0",
        "identify_songs": "INTEGER NOT NULL DEFAULT 0",
        "last_seen_post_ids_json": "TEXT NOT NULL DEFAULT '[]'",
        "last_changed_count": "INTEGER NOT NULL DEFAULT 0",
        "last_missing_count": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, type_name in monitor_migrations.items():
        if name not in monitor_columns:
            conn.execute(f"ALTER TABLE creator_monitor ADD COLUMN {name} {type_name}")
    _ensure_item_search_schema(conn)
    history_columns = {row["name"] for row in conn.execute("PRAGMA table_info(run_history)")}
    for name, type_name in _RUN_HISTORY_MIGRATIONS.items():
        if name not in history_columns:
            conn.execute(f"ALTER TABLE run_history ADD COLUMN {name} {type_name}")
    # Existing libraries used physical archive number as chronology. Preserve
    # that behavior while allowing legacy bootstrap to place collision-free
    # rows elsewhere in the filename namespace.
    conn.execute("UPDATE item SET favorite_order = id WHERE favorite_order IS NULL")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_item_favorite_order ON item(favorite_order)"
    )
    # Created after the migration loop so upgrading DBs already have song_id.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_item_song ON item(song_id) WHERE song_id IS NOT NULL"
    )
    # Additive migration for the singleton settings row (no migration dict here).
    settings_columns = {row["name"] for row in conn.execute("PRAGMA table_info(library_settings)")}
    if "song_id_enabled" not in settings_columns:
        conn.execute("ALTER TABLE library_settings ADD COLUMN song_id_enabled INTEGER NOT NULL DEFAULT 0")
    if "default_audio_name" not in settings_columns:
        conn.execute("ALTER TABLE library_settings ADD COLUMN default_audio_name TEXT")
    if "portable_metadata_enabled" not in settings_columns:
        conn.execute(
            "ALTER TABLE library_settings ADD COLUMN "
            "portable_metadata_enabled INTEGER NOT NULL DEFAULT 0"
        )
    if "local_analysis_pipeline_migrated" not in settings_columns:
        conn.execute(
            "ALTER TABLE library_settings ADD COLUMN "
            "local_analysis_pipeline_migrated INTEGER NOT NULL DEFAULT 0"
        )
        row = conn.execute(
            "SELECT phases_json FROM pipeline_setting WHERE kind = 'sync'"
        ).fetchone()
        if row is not None:
            phases = json.loads(row["phases_json"])
            if "analyze" not in phases:
                phases.append("analyze")
                conn.execute(
                    "UPDATE pipeline_setting SET phases_json = ?, updated_at = ? "
                    "WHERE kind = 'sync'",
                    (json.dumps(phases, separators=(",", ":")), _now()),
                )
        conn.execute(
            "UPDATE library_settings "
            "SET local_analysis_pipeline_migrated = 1 WHERE id = 1"
        )
    if "source_metadata_pipeline_migrated" not in settings_columns:
        conn.execute(
            "ALTER TABLE library_settings ADD COLUMN "
            "source_metadata_pipeline_migrated INTEGER NOT NULL DEFAULT 0"
        )
        row = conn.execute(
            "SELECT phases_json FROM pipeline_setting WHERE kind = 'sync'"
        ).fetchone()
        if row is not None:
            phases = json.loads(row["phases_json"])
            if "sidecars" not in phases:
                enrich_index = phases.index("enrich") + 1 if "enrich" in phases else 1
                phases.insert(enrich_index, "sidecars")
                conn.execute(
                    "UPDATE pipeline_setting SET phases_json = ?, updated_at = ? "
                    "WHERE kind = 'sync'",
                    (json.dumps(phases, separators=(",", ":")), _now()),
                )
        conn.execute(
            "UPDATE library_settings SET source_metadata_pipeline_migrated = 1 WHERE id = 1"
        )
    # Analysis rows created before in-app generation existed came from the JSON
    # importer. Register them as manual so a generated backfill can never
    # overwrite them. INSERT OR IGNORE makes this safe on every startup.
    conn.execute(
        "INSERT OR IGNORE INTO analysis_source_state "
        "(item_id, source, origin, status, media_fingerprint, attempts, "
        "last_error, attempted_at, completed_at, updated_at) "
        "SELECT item_id, source, 'manual', 'completed', NULL, 0, NULL, "
        "MIN(created_at), MIN(created_at), MIN(created_at) "
        "FROM analysis_segment GROUP BY item_id, source"
    )
    # Additive migration: remember which Spotify playlist a push created, so a
    # re-push updates it instead of duplicating.
    playlist_columns = {row["name"] for row in conn.execute("PRAGMA table_info(song_playlist)")}
    if "spotify_playlist_id" not in playlist_columns:
        conn.execute("ALTER TABLE song_playlist ADD COLUMN spotify_playlist_id TEXT")
    conn.execute(
        "UPDATE item SET search_song_text = ("
        " SELECT TRIM(COALESCE(song.title, '') || ' ' || COALESCE(song.artist, '')"
        " || ' ' || COALESCE(song.album, '')) FROM song WHERE song.id = item.song_id"
        ") WHERE song_id IS NOT NULL AND (search_song_text IS NULL OR search_song_text = '')"
    )
    item_count = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    search_count = conn.execute("SELECT COUNT(*) FROM item_search").fetchone()[0]
    if item_count and search_count != item_count:
        conn.execute("INSERT INTO item_search(item_search) VALUES ('rebuild')")
    # Adopt comment snapshots created before local comment search existed.
    # Only missing/stale documents are parsed; normal startups do no JSON work,
    # and Gallery searches always hit FTS rather than snapshot blobs.
    latest_comments = conn.execute(
        "SELECT latest.id, latest.item_id, latest.comments_json "
        "FROM comment_snapshot latest "
        "LEFT JOIN item_comment_search AS indexed_comment "
        "ON indexed_comment.item_id = latest.item_id "
        "WHERE latest.id = (SELECT MAX(candidate.id) FROM comment_snapshot candidate "
        " WHERE candidate.item_id = latest.item_id) "
        "AND (indexed_comment.snapshot_id IS NULL "
        "OR indexed_comment.snapshot_id != latest.id)"
    ).fetchall()
    for snapshot in latest_comments:
        comments = json.loads(snapshot["comments_json"])
        conn.execute(
            "INSERT INTO item_comment_search(item_id, snapshot_id, text) VALUES (?, ?, ?) "
            "ON CONFLICT(item_id) DO UPDATE SET snapshot_id = excluded.snapshot_id, "
            "text = excluded.text",
            (snapshot["item_id"], snapshot["id"], _comment_search_text(comments)),
        )
    comment_content_count = conn.execute(
        "SELECT COUNT(*) FROM item_comment_search"
    ).fetchone()[0]
    comment_index_count = conn.execute("SELECT COUNT(*) FROM comment_search").fetchone()[0]
    if comment_content_count != comment_index_count:
        conn.execute("INSERT INTO comment_search(comment_search) VALUES ('rebuild')")
    # Normalize durable snapshot JSON once so global/current/history comment
    # searches never parse blobs at request time.
    missing_entry_snapshots = conn.execute(
        "SELECT cs.id, cs.item_id, cs.comments_json FROM comment_snapshot cs "
        "LEFT JOIN comment_entry ce ON ce.snapshot_id = cs.id "
        "GROUP BY cs.id HAVING COUNT(ce.id) = 0 AND cs.saved_count > 0"
    ).fetchall()
    for snapshot in missing_entry_snapshots:
        _replace_comment_entries(
            conn, snapshot["id"], snapshot["item_id"], json.loads(snapshot["comments_json"]),
        )
    entry_count = conn.execute("SELECT COUNT(*) FROM comment_entry").fetchone()[0]
    entry_search_count = conn.execute("SELECT COUNT(*) FROM comment_entry_search").fetchone()[0]
    if entry_count != entry_search_count:
        conn.execute("INSERT INTO comment_entry_search(comment_entry_search) VALUES ('rebuild')")
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
    conn.execute(
        "INSERT OR IGNORE INTO pipeline_setting(kind, phases_json, updated_at) "
        "VALUES ('sync', ?, ?)",
        (
            json.dumps(
                ["sync", "enrich", "sidecars", "identify", "analyze"],
                separators=(",", ":"),
            ),
            _now(),
        ),
    )
    migrations.install_registry(conn)
    from core import discovery
    discovery.ensure_backfill(conn)
    conn.commit()
    return conn


# --- items -----------------------------------------------------------------

def get_item(conn, item_id):
    return conn.execute("SELECT * FROM item WHERE id = ?", (item_id,)).fetchone()


def get_item_by_link(conn, link):
    return conn.execute("SELECT * FROM item WHERE link = ?", (link,)).fetchone()


def get_item_by_video_id(conn, video_id):
    """Find a TikTok item by stable video id even if its creator handle changed."""
    rows = conn.execute(
        "SELECT * FROM item WHERE link LIKE ? OR link LIKE ?",
        (f"%/video/{video_id}%", f"%/photo/{video_id}%"),
    ).fetchall()
    for row in rows:
        match = re.search(r"/(?:video|photo)/([0-9]+)(?:[/?#]|$)", row["link"])
        if match is not None and match.group(1) == str(video_id):
            return row
    return None


def next_item_id(conn):
    """The next output number: max existing id + 1 (gaps are preserved, like the
    filesystem-based numbering it replaces)."""
    row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM item").fetchone()
    return row["m"] + 1


def next_favorite_order(conn):
    row = conn.execute("SELECT COALESCE(MAX(favorite_order), 0) AS m FROM item").fetchone()
    return row["m"] + 1


def insert_item(
    conn,
    item_id,
    link,
    favorited_at=None,
    kind="unknown",
    status="pending",
    favorite_order=None,
):
    now = _now()
    if favorite_order is None:
        favorite_order = item_id
    conn.execute(
        "INSERT INTO item (id, favorite_order, link, favorited_at, kind, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (item_id, favorite_order, link, favorited_at, kind, status, now, now),
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
    return insert_item(
        conn,
        next_item_id(conn),
        link,
        favorited_at,
        favorite_order=next_favorite_order(conn),
    )


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


def record_archive_file_health(conn, missing_ids):
    """Persist the latest integrity scan for Gallery recovery filtering."""
    missing_ids = list(dict.fromkeys(missing_ids))
    conn.execute("UPDATE item SET archive_missing = 0 WHERE archive_missing != 0")
    if missing_ids:
        placeholders = ",".join("?" for _ in missing_ids)
        conn.execute(f"UPDATE item SET archive_missing = 1 WHERE id IN ({placeholders})", missing_ids)
    conn.commit()


def reset_interrupted_downloads(conn):
    """Fold items stranded mid-download by a crash back into the retry path.

    Only one Archive run exists at a time, so any ``downloading`` row seen at
    process or run start is stale. Marking it ``failed`` makes the next Sync
    retry it and lets the existing recovery UI select it.
    """
    cursor = conn.execute(
        "UPDATE item SET status = 'failed', error = ?, updated_at = ? "
        "WHERE status = 'downloading'",
        ("interrupted: the app stopped mid-download", _now()),
    )
    conn.commit()
    return cursor.rowcount


def item_ids_in_range(conn, first_id, last_id):
    """Existing item ids inside an inclusive archive-number range."""
    return [row["id"] for row in conn.execute(
        "SELECT id FROM item WHERE id BETWEEN ? AND ? ORDER BY id",
        (int(first_id), int(last_id)),
    )]


def item_ids_matching(conn, **query):
    """Ids of every item matching a Gallery filter query (no paging)."""
    for key in ("limit", "cursor", "order", "seed"):
        if query.get(key) is not None and query.get(key) != PAGE_QUERY_DEFAULTS[key]:
            raise ValueError(f"{key} is not a filter")
    q, clauses, params, fts_query = _page_query_base(query, "item")
    sql, params = _page_sql("id", clauses, params, fts_query, q["search_scope"])
    return [row["id"] for row in conn.execute(sql + " ORDER BY id", params)]


_MARK_CHUNK = 500  # stay under SQLite's bound-parameter limit


def _id_chunks(item_ids):
    ids = [int(item_id) for item_id in item_ids]
    for start in range(0, len(ids), _MARK_CHUNK):
        yield ids[start:start + _MARK_CHUNK]


def is_redownloadable(row):
    """A Favorite whose media can be fetched again from its source link.

    Synthetic ``local://`` items exist only to represent a file, and offloaded
    items live outside this archive — neither has anything to re-download.
    """
    return not str(row["link"]).startswith("local://") and not row["offloaded"]


def offloaded_ids(conn, item_ids):
    """The subset of item_ids currently marked offloaded, in id order."""
    found = []
    for chunk in _id_chunks(item_ids):
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT id FROM item WHERE id IN ({placeholders}) AND offloaded = 1 ORDER BY id",
            chunk,
        ).fetchall()
        found.extend(row["id"] for row in rows)
    return found


def set_offloaded(conn, item_ids, offloaded=True):
    """Mark media as archived externally (or clear the mark). Returns changed count."""
    now = _now()
    changed = 0
    for chunk in _id_chunks(item_ids):
        placeholders = ",".join("?" for _ in chunk)
        if offloaded:
            cursor = conn.execute(
                f"UPDATE item SET offloaded = 1, status = 'done', error = NULL, "
                f"archive_missing = 0, updated_at = ? WHERE id IN ({placeholders}) "
                "AND (offloaded != 1 OR status != 'done' OR error IS NOT NULL OR archive_missing != 0)",
                (now, *chunk),
            )
        else:
            cursor = conn.execute(
                f"UPDATE item SET offloaded = 0, updated_at = ? "
                f"WHERE id IN ({placeholders}) AND offloaded = 1",
                (now, *chunk),
            )
        changed += cursor.rowcount
    conn.commit()
    return changed


def set_ignored(conn, item_ids, ignored=True):
    """User-set 'never download' terminal status (or restore to pending)."""
    now = _now()
    changed = 0
    for chunk in _id_chunks(item_ids):
        placeholders = ",".join("?" for _ in chunk)
        if ignored:
            cursor = conn.execute(
                f"UPDATE item SET status = 'ignored', error = NULL, updated_at = ? "
                f"WHERE id IN ({placeholders}) AND status IN ('pending', 'failed')",
                (now, *chunk),
            )
        else:
            cursor = conn.execute(
                f"UPDATE item SET status = 'pending', updated_at = ? "
                f"WHERE id IN ({placeholders}) AND status = 'ignored'",
                (now, *chunk),
            )
        changed += cursor.rowcount
    conn.commit()
    return changed


def range_status_summary(conn, first_id, last_id):
    """Status counts inside an inclusive id range, for the offload suggestion."""
    row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN status IN ('pending','failed') THEN 1 ELSE 0 END) AS undownloaded, "
        "SUM(CASE WHEN offloaded = 1 THEN 1 ELSE 0 END) AS already_offloaded "
        "FROM item WHERE id BETWEEN ? AND ?",
        (int(first_id), int(last_id)),
    ).fetchone()
    return {
        "total": int(row["total"] or 0),
        "undownloaded": int(row["undownloaded"] or 0),
        "already_offloaded": int(row["already_offloaded"] or 0),
    }


def set_metadata(conn, item_id, caption, author):
    from core import discovery
    with conn:
        conn.execute(
            "UPDATE item SET caption = ?, author = ?, enrich_status = 'ok', updated_at = ? WHERE id = ?",
            (caption, author, _now(), item_id),
        )
        discovery.upsert_item_identities(conn, item_id, author, caption)


def set_source_metadata(conn, item_id, metadata, source_thumbnail_path=None):
    """Persist normalized extractor facts and refresh exact discovery identities."""
    from core import discovery
    fields = {
        "caption": metadata.title,
        "author": metadata.creator_display_name or metadata.creator_username,
        "description": metadata.description,
        "source_posted_at": metadata.posted_at,
        "creator_username": metadata.creator_username,
        "creator_external_id": metadata.creator_id,
        "creator_url": metadata.creator_url,
        "source_duration_s": metadata.duration_s,
        "source_width": metadata.width,
        "source_height": metadata.height,
        "view_count": metadata.view_count,
        "like_count": metadata.like_count,
        "comment_count": metadata.comment_count,
        "repost_count": metadata.repost_count,
        "save_count": metadata.save_count,
        "source_thumbnail_path": source_thumbnail_path,
        "source_info_status": "ok",
        "source_info_at": _now(),
        "source_info_error": None,
        "comments_status": (
            "ok" if metadata.comments_attempted or metadata.comment_count in (None, 0)
            else "pending"
        ),
        "enrich_status": "ok",
        "updated_at": _now(),
    }
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with conn:
        conn.execute(
            f"UPDATE item SET {assignments} WHERE id = ?",
            (*fields.values(), item_id),
        )
        discovery.upsert_item_identities(
            conn,
            item_id,
            fields["author"],
            metadata.description or metadata.title,
            creator_key=metadata.creator_username,
            creator_display=fields["author"],
        )


def set_source_metadata_unavailable(conn, item_id, error=None):
    _update(
        conn,
        item_id,
        source_info_status="unavailable",
        source_info_at=_now(),
        source_info_error=str(error) if error else None,
    )


def items_needing_source_metadata(conn, recheck=False):
    sql = "SELECT * FROM item WHERE link NOT LIKE 'local://%'"
    if not recheck:
        sql += " AND (source_info_status IS NULL OR comments_status = 'pending')"
    return conn.execute(sql + " ORDER BY id").fetchall()


def record_portable_metadata(conn, item_id, content_hash, file_size=None,
                             fingerprint=None):
    _update(
        conn, item_id, portable_metadata_status="ok",
        portable_metadata_hash=content_hash, portable_metadata_at=_now(),
        portable_metadata_error=None,
        **({"media_size": file_size} if file_size is not None else {}),
        **({"media_fingerprint": fingerprint} if fingerprint is not None else {}),
    )


def record_portable_metadata_error(conn, item_id, error):
    _update(
        conn, item_id, portable_metadata_status="error",
        portable_metadata_at=_now(), portable_metadata_error=str(error),
    )


def _comment_identity(comment):
    comment_id = str(comment.get("id") or "").strip()
    if comment_id:
        return "id:" + comment_id
    return "value:" + json.dumps(
        [
            comment.get("parent"), comment.get("author_id"),
            comment.get("author_username"), comment.get("text"),
            comment.get("timestamp"),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def record_comment_snapshot(conn, item_id, comments, reported_count=None,
                            captured_at=None):
    """Append one local comment observation and summarize it against the prior one."""
    comments = [dict(comment) for comment in comments if isinstance(comment, dict)]
    previous = conn.execute(
        "SELECT comments_json FROM comment_snapshot WHERE item_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (item_id,),
    ).fetchone()
    before_comments = json.loads(previous["comments_json"]) if previous else []
    before = {_comment_identity(comment): comment for comment in before_comments}
    after = {_comment_identity(comment): comment for comment in comments}
    shared = before.keys() & after.keys()
    added = len(after.keys() - before.keys())
    removed = len(before.keys() - after.keys())
    changed = sum(before[key] != after[key] for key in shared)
    captured_at = captured_at or _now()
    cursor = conn.execute(
        "INSERT INTO comment_snapshot "
        "(item_id, captured_at, comments_json, saved_count, reported_count, "
        "added_count, removed_count, changed_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            item_id, captured_at,
            json.dumps(comments, ensure_ascii=False, separators=(",", ":")),
            len(comments), reported_count, added, removed, changed,
        ),
    )
    snapshot_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO item_comment_search(item_id, snapshot_id, text) VALUES (?, ?, ?) "
        "ON CONFLICT(item_id) DO UPDATE SET snapshot_id = excluded.snapshot_id, "
        "text = excluded.text",
        (item_id, snapshot_id, _comment_search_text(comments)),
    )
    _replace_comment_entries(conn, snapshot_id, item_id, comments)
    conn.commit()
    return snapshot_id


def list_comment_snapshots(conn, item_id):
    rows = conn.execute(
        "SELECT * FROM comment_snapshot WHERE item_id = ? ORDER BY id DESC",
        (item_id,),
    ).fetchall()
    return [
        {
            "id": row["id"], "captured_at": row["captured_at"],
            "comments": json.loads(row["comments_json"]),
            "saved_count": row["saved_count"],
            "reported_count": row["reported_count"],
            "changes": {
                "added": row["added_count"], "removed": row["removed_count"],
                "changed": row["changed_count"],
            },
        }
        for row in rows
    ]


def set_metadata_unavailable(conn, item_id):
    """Remember that enrichment ran and oEmbed returned nothing.

    NULL ``enrich_status`` = never attempted; ``'unavailable'`` is remembered so
    an automatic (Sync-chained) enrich skips it, while an explicit backfill
    (``recheck``) still retries it. Mirrors ``set_item_song_no_match``.
    """
    _update(conn, item_id, enrich_status="unavailable")


def items_needing_enrichment(conn, recheck=False):
    """Items with a real link and no caption yet (skips synthetic local:// files).

    NULL ``enrich_status`` = never attempted. An item that was tried but returned
    no metadata is marked ``'unavailable'`` and skipped on automatic runs so a
    Sync no longer re-hits oEmbed for the whole caption-less backlog every time;
    ``recheck`` (the explicit backfill) drops that filter and retries them all.
    """
    sql = (
        "SELECT * FROM item "
        "WHERE caption IS NULL AND link NOT LIKE 'local://%'"
    )
    if not recheck:
        sql += " AND enrich_status IS NULL"
    sql += " ORDER BY id"
    return conn.execute(sql).fetchall()


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
    if "download_source" in outcome:
        fields["download_source"] = outcome["download_source"]
    fields["last_attempt_at"] = _now()
    assignments = ", ".join(f"{col} = ?" for col in fields)
    conn.execute(
        f"UPDATE item SET {assignments}, attempt_count = attempt_count + 1, updated_at = ? WHERE id = ?",
        (*fields.values(), _now(), item_id),
    )
    conn.commit()


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
        has_audio=1 if index.get("has_audio", True) else 0,
        audio_silent=None if index.get("audio_silent") is None else (1 if index.get("audio_silent") else 0),
        media_fingerprint=fingerprint,
        indexed_at=_now(),
        index_error=None,
    )


def record_media_index_error(conn, item_id, error):
    """Keep a failed index retryable while retaining the failure reason."""
    _update(conn, item_id, index_error=error)


def items_needing_audio_repair(conn):
    return conn.execute(
        "SELECT * FROM item WHERE status = 'done' AND offloaded = 0 "
        "AND link NOT LIKE 'local://%' "
        "AND (has_audio = 0 OR audio_silent = 1) ORDER BY id"
    ).fetchall()


def record_audio_repair(conn, item_id, index, fingerprint):
    """Commit verified repaired media facts without changing Archive identity."""
    record_manual_media(conn, item_id, index=index, fingerprint=fingerprint)
    _update(conn, item_id, download_source="yt-dlp")


def record_manual_media(conn, item_id, index=None, fingerprint=None, custom_thumbnail_path=None):
    """Commit facts for user-supplied media without changing archive identity."""
    fields = {}
    if index is not None:
        fields.update(
            status="done",
            error=None,
            archive_missing=0,
            offloaded=0,
            thumbnail_path=index["thumbnail_path"],
            duration_s=index["duration_s"],
            media_width=index["width"],
            media_height=index["height"],
            media_codec=index["codec"],
            media_size=index["file_size"],
            has_audio=1 if index["has_audio"] else 0,
            audio_silent=None if index.get("audio_silent") is None else (1 if index.get("audio_silent") else 0),
            media_fingerprint=fingerprint,
            indexed_at=_now(),
            index_error=None,
        )
    if custom_thumbnail_path is not None:
        fields["custom_thumbnail_path"] = custom_thumbnail_path
    if not fields:
        return
    # A replacement video or poster invalidates the previously embedded copy;
    # the next opt-in sidecar run will rebuild it from the new local files.
    fields.update(
        portable_metadata_status=None,
        portable_metadata_hash=None,
        portable_metadata_at=None,
        portable_metadata_error=None,
    )
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{column} = ?" for column in fields)
    conn.execute(
        f"UPDATE item SET {assignments} WHERE id = ?",
        (*fields.values(), item_id),
    )
    conn.commit()


# --- song identification ----------------------------------------------------

def upsert_song(conn, dedup_key, title, artist=None, album=None, art_url=None,
                shazam_url=None, apple_url=None, spotify_url=None, shazam_key=None):
    """Insert a song (deduped by ``dedup_key``) and return its id.

    A repeat identification of the same track reuses the existing row, so the
    Music view can list each distinct song once with the favorites that use it.
    """
    conn.execute(
        "INSERT OR IGNORE INTO song "
        "(dedup_key, shazam_key, title, artist, album, art_url, shazam_url, apple_url, spotify_url, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (dedup_key, shazam_key, title, artist, album, art_url, shazam_url, apple_url, spotify_url, _now()),
    )
    conn.commit()
    return conn.execute("SELECT id FROM song WHERE dedup_key = ?", (dedup_key,)).fetchone()["id"]


def get_song(conn, song_id):
    return conn.execute("SELECT * FROM song WHERE id = ?", (song_id,)).fetchone()


def get_items(conn, item_ids):
    """Items by id in one query -> {id: row}. Missing ids are simply absent."""
    ids = sorted({int(item_id) for item_id in item_ids})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(f"SELECT * FROM item WHERE id IN ({placeholders})", ids).fetchall()
    return {row["id"]: row for row in rows}


def get_songs(conn, song_ids):
    """Songs by id in one query -> {id: row}. Kills the per-item N+1 when a
    Gallery page of song-bearing favorites is projected."""
    ids = sorted({int(song_id) for song_id in song_ids})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(f"SELECT * FROM song WHERE id IN ({placeholders})", ids).fetchall()
    return {row["id"]: row for row in rows}


def set_item_song(conn, item_id, song_id, source="auto"):
    """Attach an identified song to an item and mark it identified."""
    song = get_song(conn, song_id)
    if song is None:
        raise KeyError(song_id)
    search_text = " ".join(
        value.strip() for value in (song["title"], song["artist"], song["album"])
        if isinstance(value, str) and value.strip()
    )
    _update(conn, item_id, song_id=song_id, song_status="identified",
            song_source=source, song_identified_at=_now(), song_error=None,
            search_song_text=search_text)


def set_item_song_no_match(conn, item_id):
    """Remember that identification ran and found nothing, so re-runs skip it."""
    _update(conn, item_id, song_id=None, song_status="no_match",
            song_identified_at=_now(), song_error=None, search_song_text=None)


def set_item_song_error(conn, item_id, error):
    """Record an identification failure; kept retryable, keeps the reason."""
    _update(conn, item_id, song_status="error", song_error=str(error)[:500])


def items_needing_identification(conn, retry_no_match=False):
    """Finished, audio-bearing local items whose song is not yet resolved.

    NULL ``song_status`` = never attempted. ``'no_match'`` is remembered so a
    re-run does not re-hammer Shazam (unless ``retry_no_match``); ``'error'`` is
    always retried. Only confirmed audio-less items (``has_audio = 0``) are
    skipped — NULL means the item was never indexed for audio (or was indexed
    before audio detection existed), so it is still eligible.
    """
    skip = ["identified"]
    if not retry_no_match:
        skip.append("no_match")
    placeholders = ",".join("?" for _ in skip)
    return conn.execute(
        "SELECT * FROM item WHERE status = 'done' AND offloaded = 0 AND archive_missing = 0 "
        "AND (has_audio = 1 OR has_audio IS NULL) "
        f"AND (song_status IS NULL OR song_status NOT IN ({placeholders})) "
        "ORDER BY id",
        tuple(skip),
    ).fetchall()


def distinct_songs(conn, item_cap=100):
    """Every identified song with how many favorites use it, most-used first.

    Each entry carries up to ``item_cap`` of its favorites' ids so the Music view
    can open them as a Feed queue. Songs used by no (remaining) item are omitted.
    """
    songs = conn.execute(
        "SELECT s.*, COUNT(i.id) AS uses "
        "FROM song s JOIN item i ON i.song_id = s.id "
        "GROUP BY s.id ORDER BY uses DESC, s.title COLLATE NOCASE, s.id"
    ).fetchall()
    ids_by_song = {}
    for row in conn.execute(
        "SELECT song_id, id FROM item WHERE song_id IS NOT NULL ORDER BY song_id, id"
    ):
        ids = ids_by_song.setdefault(row["song_id"], [])
        if len(ids) < item_cap:
            ids.append(row["id"])
    return [
        {
            "id": song["id"],
            "title": song["title"],
            "artist": song["artist"],
            "album": song["album"],
            "art_url": song["art_url"],
            "shazam_url": song["shazam_url"],
            "apple_url": song["apple_url"],
            "spotify_url": song["spotify_url"],
            "uses": song["uses"],
            "item_ids": ids_by_song.get(song["id"], []),
        }
        for song in songs
    ]


def has_items(conn):
    """True when at least one Archive item row exists."""
    return conn.execute("SELECT 1 FROM item LIMIT 1").fetchone() is not None


def bulk_insert_items(conn, rows):
    """Insert fully-specified Archive item rows in one all-or-nothing transaction.

    For the legacy bootstrap: each row dict carries an explicit ``id`` and
    ``favorite_order`` (plus ``link``/``favorited_at``/``status`` and optional
    ``error``/``offloaded``). All rows share one timestamp; any failure rolls
    the whole batch back.
    """
    now = _now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            "INSERT INTO item "
            "(id, favorite_order, link, favorited_at, kind, status, error, offloaded, created_at, updated_at) "
            "VALUES (:id, :favorite_order, :link, :favorited_at, 'unknown', :status, :error, :offloaded, "
            ":created_at, :updated_at)",
            [
                {"error": None, "offloaded": 0, **row, "created_at": now, "updated_at": now}
                for row in rows
            ],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def items_needing_index(conn):
    """Finished Archive items without a persisted Gallery index."""
    return conn.execute(
        "SELECT * FROM item WHERE status = 'done' AND offloaded = 0 AND "
        "(thumbnail_path IS NULL OR has_audio IS NULL) ORDER BY id"
    ).fetchall()


def items_for_index_rebuild(conn):
    """Finished local media eligible for an explicit full index rebuild."""
    return conn.execute(
        "SELECT * FROM item WHERE status = 'done' AND offloaded = 0 ORDER BY id"
    ).fetchall()


def items_by_status(conn, statuses):
    placeholders = ",".join("?" for _ in statuses)
    return conn.execute(
        f"SELECT * FROM item WHERE status IN ({placeholders}) ORDER BY id",
        tuple(statuses),
    ).fetchall()


def all_items(conn):
    return conn.execute("SELECT * FROM item ORDER BY id").fetchall()


def request_creator_enrichment(conn, item_id, *, analyze=False, identify=False):
    conn.execute(
        "UPDATE item SET creator_analyze_requested = MAX(creator_analyze_requested, ?), "
        "creator_identify_requested = MAX(creator_identify_requested, ?), updated_at = ? WHERE id = ?",
        (1 if analyze else 0, 1 if identify else 0, _now(), int(item_id)),
    )
    conn.commit()


def creator_enrichment_ids(conn, field):
    if field not in ("creator_analyze_requested", "creator_identify_requested"):
        raise ValueError("unknown creator enrichment field")
    return [row["id"] for row in conn.execute(
        f"SELECT id FROM item WHERE {field} = 1 AND status = 'done' ORDER BY id"
    )]


def clear_creator_enrichment(conn, field, item_ids):
    if field not in ("creator_analyze_requested", "creator_identify_requested"):
        raise ValueError("unknown creator enrichment field")
    ids = [int(value) for value in item_ids]
    if ids:
        conn.execute(
            f"UPDATE item SET {field} = 0 WHERE id IN ({','.join('?' for _ in ids)})",
            ids,
        )
        conn.commit()


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


def _scoped_fts_query(query, search_scope):
    match = _fts_query(query)
    if not match:
        return ""
    if search_scope == "posts":
        return (
            "{caption author link description creator_username} : ("
            + match + ")"
        )
    if search_scope == "songs":
        return "search_song_text : (" + match + ")"
    return match


def _scope_fts_match(match, search_scope):
    if not match:
        return ""
    if search_scope == "posts":
        return "{caption author link description creator_username} : (" + match + ")"
    if search_scope == "songs":
        return "search_song_text : (" + match + ")"
    return match


def _advanced_search_clauses(parsed):
    """Compile explicit field terms to indexed item predicates."""
    clauses, params = [], []
    aliases = {"text": "comment", "comments": "comment", "author": "creator"}
    allowed = {"creator", "comment", "song", "transcript", "ocr", "views", "likes", "comments_count", "posted", "has"}
    for raw_field, tokens in parsed.fields.items():
        field = aliases.get(raw_field, raw_field)
        if field not in allowed:
            raise ValueError(f"unknown search field: {raw_field}")
        for token in tokens:
            negate = token.negative
            if field == "creator":
                clause = "LOWER(COALESCE(creator_username, author, '')) LIKE ?"
                value_params = [f"%{token.value.casefold()}%"]
            elif field in ("comment", "song"):
                match = structured_search.fts_query((structured_search.SearchToken(token.value, False, token.phrase),))
                table = "comment_search" if field == "comment" else "item_search"
                scope = "" if field == "comment" else "search_song_text : "
                clause = f"EXISTS (SELECT 1 FROM {table} WHERE {table}.rowid = item.id AND {table} MATCH ?)"
                value_params = [scope + f"({match})" if scope else match]
            elif field in ("transcript", "ocr"):
                match = structured_search.fts_query((structured_search.SearchToken(token.value, False, token.phrase),))
                clause = (
                    "EXISTS (SELECT 1 FROM analysis_search JOIN analysis_segment aseg "
                    "ON analysis_search.rowid = aseg.id WHERE aseg.item_id = item.id "
                    "AND aseg.source = ? AND analysis_search MATCH ?)"
                )
                value_params = [field, match]
            elif field in ("views", "likes", "comments_count"):
                operator, number = structured_search.comparison(token.value)
                column = {"views": "view_count", "likes": "like_count", "comments_count": "comment_count"}[field]
                clause, value_params = f"{column} {operator} ?", [number]
            elif field == "posted":
                if not re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", token.value):
                    raise ValueError("posted expects YYYY, YYYY-MM, or YYYY-MM-DD")
                clause, value_params = "source_posted_at LIKE ?", [token.value + "%"]
            else:
                has = {
                    "comments": "comments_status = 'ok'",
                    "audio": "has_audio = 1 AND COALESCE(audio_silent, 0) = 0",
                    "thumbnail": "thumbnail_path IS NOT NULL",
                    "transcript": "EXISTS (SELECT 1 FROM analysis_source_state ast WHERE ast.item_id=item.id AND ast.source='transcript' AND ast.status='ok')",
                    "ocr": "EXISTS (SELECT 1 FROM analysis_source_state ast WHERE ast.item_id=item.id AND ast.source='ocr' AND ast.status='ok')",
                    "song": "song_id IS NOT NULL",
                    "source": "source_info_status = 'ok'",
                    "offline": "status = 'done'",
                }.get(token.value.casefold())
                if has is None:
                    raise ValueError(f"unknown has value: {token.value}")
                clause, value_params = has, []
            clauses.append(f"NOT ({clause})" if negate else clause)
            params.extend(value_params)
    return clauses, params


_SUGGEST_STOPWORDS = frozenset({
    "the", "and", "for", "you", "your", "this", "that", "with", "was", "are",
    "day", "part", "how", "its", "out", "all", "not", "but", "one", "get",
})


def suggest(conn, q, limit=6):
    """Typeahead suggestions grounded in the archive: creators and hashtags that
    actually occur, plus a few caption keywords. Every candidate is matched
    against the last word being typed and ranked by how many favorites contain
    it, so the list only ever offers things the library really has."""
    tokens = re.findall(r"[a-z0-9_]+", (q or "").lower())
    if not tokens:
        return {"creators": [], "hashtags": [], "terms": []}
    match = _fts_query(" ".join(tokens))  # one safe-FTS-expression builder
    try:
        rows = conn.execute(
            "SELECT item.author AS author, item.caption AS caption "
            "FROM item_search JOIN item ON item_search.rowid = item.id "
            "WHERE item_search MATCH ? LIMIT 1000",
            (match,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {"creators": [], "hashtags": [], "terms": []}

    needle = tokens[-1]
    creators, hashtags, terms = {}, {}, {}
    for row in rows:
        author = row["author"]
        if author and re.sub(r"[^a-z0-9_]", "", author.lower()).startswith(needle):
            creators[author] = creators.get(author, 0) + 1
        caption = (row["caption"] or "").lower()
        for tag in re.findall(r"#(\w+)", caption):
            if tag.startswith(needle):
                hashtags["#" + tag] = hashtags.get("#" + tag, 0) + 1
        for word in re.findall(r"(?<![#\w])([a-z][a-z0-9_]{2,})", caption):
            if word.startswith(needle) and word not in _SUGGEST_STOPWORDS:
                terms[word] = terms.get(word, 0) + 1

    for word in list(terms):  # a word already offered as a hashtag is redundant
        if "#" + word in hashtags:
            del terms[word]

    state = migrations.get_backfill(conn, "discovery-identities-v1")
    if state is not None and state["status"] == "completed":
        creators = {
            row["display_name"]: row["c"] for row in conn.execute(
                "SELECT c.display_name, COUNT(*) AS c FROM creator c "
                "JOIN item i ON i.creator_id = c.id WHERE c.canonical_key LIKE ? "
                "GROUP BY c.id", (needle + "%",),
            )
        }
        hashtags = {
            row["display_name"]: row["c"] for row in conn.execute(
                "SELECT h.display_name, COUNT(*) AS c FROM hashtag h "
                "JOIN item_hashtag ih ON ih.hashtag_id = h.id "
                "WHERE h.canonical_key LIKE ? GROUP BY h.id", (needle + "%",),
            )
        }

    def top(counts, count):
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return [{"value": value, "count": total} for value, total in ranked[:count]]

    return {"creators": top(creators, limit), "hashtags": top(hashtags, limit), "terms": top(terms, 3)}


_PAGE_ORDERS = {
    "latest": ("favorite_order DESC, id DESC", "favorite_order", "DESC"),
    "archive": ("favorite_order ASC, id ASC", "favorite_order", "ASC"),
    "size_desc": ("media_size DESC, id DESC", "media_size", "DESC"),
    "duration_desc": ("duration_s DESC, id DESC", "duration_s", "DESC"),
    "duration_asc": ("duration_s ASC, id ASC", "duration_s", "ASC"),
    "favorite_date_desc": ("favorited_at DESC, id DESC", "favorited_at", "DESC"),
    "favorite_date_asc": ("favorited_at ASC, id ASC", "favorited_at", "ASC"),
    "attempts_desc": ("attempt_count DESC, id DESC", "attempt_count", "DESC"),
    "last_attempt_desc": ("last_attempt_at DESC, id DESC", "last_attempt_at", "DESC"),
    "author_asc": ("author ASC, id ASC", "author", "ASC"),
    "audio_missing": (
        "CASE WHEN (has_audio = 0 OR audio_silent = 1) THEN 0 WHEN has_audio = 1 THEN 1 ELSE 2 END ASC, id DESC",
        None,
        None,
    ),
    "relevance": ("rank ASC, id DESC", None, None),
}

# The user-selectable order names, in one place. "relevance" is internal — it
# is auto-selected when a text query is present; "random" is valid but lives
# outside _PAGE_ORDERS (its ORDER BY is generated per seed).
SELECTABLE_ORDERS = tuple(name for name in _PAGE_ORDERS if name != "relevance") + ("random",)

# Seeded shuffle for random paging: ordering by an avalanche hash of
# (id XOR seed mask) is a stable permutation per seed, so cursor pages never
# repeat an item the way ORDER BY RANDOM() pages would. The hash is the
# standard xorshift-multiply 32-bit bijection; every intermediate stays well
# inside SQLite's 64-bit integers, because overflow would silently degrade the
# SQL keys to inexact REALs and break the cursor comparison. SQLite has no XOR
# operator, so the generated SQL spells XOR as (a|b) - (a&b).
_RANDOM_MODULUS = 2**32
_RANDOM_HASH_MULTIPLIER = 0x45D9F3B


def _random_mask(seed):
    z = (int(seed) + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return (z ^ (z >> 31)) % _RANDOM_MODULUS


def _random_order_key(item_id, seed):
    x = (int(item_id) ^ _random_mask(seed)) % _RANDOM_MODULUS
    for _ in range(2):
        x = ((x ^ (x >> 16)) * _RANDOM_HASH_MULTIPLIER) % _RANDOM_MODULUS
    return x ^ (x >> 16)


def _random_key_sql(seed):
    def xor(a, b):
        return f"(({a} | {b}) - ({a} & {b}))"

    x = xor("id", str(_random_mask(seed)))
    for _ in range(2):
        x = f"(({xor(f'({x} >> 16)', x)} * {_RANDOM_HASH_MULTIPLIER}) % {_RANDOM_MODULUS})"
    return xor(f"({x} >> 16)", x)


# Every filter/sort kwarg page_items accepts, with its default. Adding a
# Gallery filter = one entry here + one clause in _page_filter_clauses.
PAGE_QUERY_DEFAULTS = {
    "query": None,
    "search_scope": "posts",
    "kinds": None,
    "statuses": None,
    "limit": 50,
    "cursor": None,
    "order": "latest",
    "min_duration": None,
    "max_duration": None,
    "min_size": None,
    "max_size": None,
    "min_width": None,
    "max_width": None,
    "min_height": None,
    "max_height": None,
    "codecs": None,
    "date_from": None,
    "date_to": None,
    "posted_from": None,
    "posted_to": None,
    "min_views": None,
    "min_likes": None,
    "min_comments": None,
    "source_info": None,
    "comments_state": None,
    "download_source": None,
    "portable_metadata": None,
    "orientations": None,
    "has_assets": None,
    "has_audio": None,
    "index_state": None,
    "include": None,
    "exclude": None,
    "min_attempts": None,
    "max_attempts": None,
    "recovery": False,
    "offloaded": None,
    "seed": None,
    "feed": False,
    "creator_key": None,
    "hashtag_key": None,
    "song_id": None,
    "starred": None,
    "private_tag_key": None,
}


def _page_filter_clauses(q):
    """WHERE fragments + params for the straight-line Gallery filters."""
    clauses = []
    params = []
    if q["feed"]:
        clauses.append("(status IN ('done', 'expired') OR offloaded = 1)")
    if q["min_duration"] is not None:
        clauses.append("duration_s >= ?")
        params.append(float(q["min_duration"]))
    if q["max_duration"] is not None:
        clauses.append("duration_s <= ?")
        params.append(float(q["max_duration"]))
    if q["min_size"] is not None:
        clauses.append("media_size >= ?")
        params.append(int(q["min_size"]))
    if q["max_size"] is not None:
        clauses.append("media_size <= ?")
        params.append(int(q["max_size"]))
    if q["min_width"] is not None:
        clauses.append("media_width >= ?")
        params.append(int(q["min_width"]))
    if q["max_width"] is not None:
        clauses.append("media_width <= ?")
        params.append(int(q["max_width"]))
    if q["min_height"] is not None:
        clauses.append("media_height >= ?")
        params.append(int(q["min_height"]))
    if q["max_height"] is not None:
        clauses.append("media_height <= ?")
        params.append(int(q["max_height"]))
    if q["min_attempts"] is not None:
        clauses.append("attempt_count >= ?")
        params.append(int(q["min_attempts"]))
    if q["max_attempts"] is not None:
        clauses.append("attempt_count <= ?")
        params.append(int(q["max_attempts"]))
    if q["recovery"]:
        clauses.append("(status = 'failed' OR archive_missing = 1 OR (status = 'pending' AND attempt_count = 0))")
    if q["offloaded"] is not None:
        clauses.append("offloaded = ?")
        params.append(1 if q["offloaded"] else 0)
    if q["codecs"]:
        clauses.append("media_codec IN (%s)" % ",".join("?" for _ in q["codecs"]))
        params += list(q["codecs"])
    if q["date_from"]:
        clauses.append("favorited_at >= ?")
        params.append(q["date_from"])
    if q["date_to"]:
        clauses.append("favorited_at <= ?")
        params.append(q["date_to"])
    if q["posted_from"]:
        clauses.append("source_posted_at >= ?")
        params.append(q["posted_from"])
    if q["posted_to"]:
        clauses.append("source_posted_at <= ?")
        params.append(q["posted_to"])
    for key, column in (
        ("min_views", "view_count"),
        ("min_likes", "like_count"),
        ("min_comments", "comment_count"),
    ):
        if q[key] is not None:
            clauses.append(f"{column} >= ?")
            params.append(int(q[key]))
    source_info_filters = {
        "saved": "source_info_status = 'ok'",
        "unavailable": "source_info_status = 'unavailable'",
        "missing": "source_info_status IS NULL",
    }
    if q["source_info"]:
        clauses.append(source_info_filters[q["source_info"]])
    comments_filters = {
        "saved": "comments_status = 'ok'",
        "with_comments": (
            "EXISTS (SELECT 1 FROM item_comment_search ics "
            "WHERE ics.item_id = item.id AND ics.text <> '')"
        ),
        "missing": "(comments_status IS NULL OR comments_status <> 'ok')",
    }
    if q["comments_state"]:
        clauses.append(comments_filters[q["comments_state"]])
    download_source_filters = {
        "cobalt": "download_source = 'cobalt'",
        "yt-dlp": "download_source = 'yt-dlp'",
        "legacy": "(download_source IS NULL OR download_source NOT IN ('cobalt', 'yt-dlp'))",
    }
    if q["download_source"]:
        clauses.append(download_source_filters[q["download_source"]])
    portable_metadata_filters = {
        "embedded": "portable_metadata_status = 'ok'",
        "failed": "portable_metadata_status = 'error'",
        "missing": "portable_metadata_status IS NULL",
    }
    if q["portable_metadata"]:
        clauses.append(portable_metadata_filters[q["portable_metadata"]])
    if q["orientations"]:
        orientation_sql = {
            "portrait": "media_height > media_width",
            "landscape": "media_width > media_height",
            "square": "media_width = media_height",
        }
        selected = [orientation_sql[name] for name in q["orientations"] if name in orientation_sql]
        if selected:
            clauses.append("(" + " OR ".join(selected) + ")")
    if q["has_assets"] is not None:
        clauses.append("has_assets = ?")
        params.append(1 if q["has_assets"] else 0)
    if q["has_audio"] is not None:
        # "No audio" = no stream at all, OR a stream that is silent (all-zero /
        # inaudible). "Has audio" = a stream that is not known-silent.
        if q["has_audio"]:
            clauses.append("(has_audio = 1 AND (audio_silent = 0 OR audio_silent IS NULL))")
        else:
            clauses.append("(has_audio = 0 OR audio_silent = 1)")
    if q["creator_key"]:
        clauses.append(
            "creator_id = (SELECT id FROM creator WHERE canonical_key = ?)"
        )
        params.append(q["creator_key"])
    if q["hashtag_key"]:
        clauses.append(
            "EXISTS (SELECT 1 FROM item_hashtag ih JOIN hashtag h "
            "ON h.id = ih.hashtag_id WHERE ih.item_id = item.id "
            "AND h.canonical_key = ?)"
        )
        params.append(q["hashtag_key"])
    if q["song_id"] is not None:
        clauses.append("song_id = ?")
        params.append(int(q["song_id"]))
    if q["starred"] is not None:
        if q["starred"]:
            clauses.append(
                "EXISTS (SELECT 1 FROM item_annotation ia "
                "WHERE ia.item_id = item.id AND ia.starred = 1)"
            )
        else:
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM item_annotation ia "
                "WHERE ia.item_id = item.id AND ia.starred = 1)"
            )
    if q["private_tag_key"]:
        clauses.append(
            "EXISTS (SELECT 1 FROM item_private_tag ipt "
            "JOIN private_tag pt ON pt.id = ipt.tag_id "
            "WHERE ipt.item_id = item.id AND pt.canonical_key = ?)"
        )
        params.append(q["private_tag_key"])
    index_filters = {
        "indexed": "thumbnail_path IS NOT NULL",
        "missing": "thumbnail_path IS NULL AND index_error IS NULL",
        "failed": "index_error IS NOT NULL",
    }
    if q["index_state"] in index_filters:
        clauses.append(index_filters[q["index_state"]])
    for term in q["include"] or []:
        clauses.append("(caption LIKE ? OR author LIKE ?)")
        params += [f"%{term}%", f"%{term}%"]
    for term in q["exclude"] or []:
        clauses.append("NOT (caption LIKE ? OR author LIKE ?)")
        params += [f"%{term}%", f"%{term}%"]
    return clauses, params


def _page_query_base(query, caller):
    """Validate + merge one Gallery query -> (q, clauses, params, fts_query).

    The single filter-construction path shared by ``page_items``, ``feed_ids``
    and ``item_ids_matching`` — a new filter lands in ``_page_filter_clauses``
    once and every query shape picks it up.
    """
    unknown = set(query) - set(PAGE_QUERY_DEFAULTS)
    if unknown:
        raise ValueError(f"unknown {caller} filters: " + ", ".join(sorted(unknown)))
    q = {**PAGE_QUERY_DEFAULTS, **query}
    if q["search_scope"] not in ("posts", "comments", "songs", "analysis", "all"):
        raise ValueError("unknown search scope")
    filter_values = {
        "source_info": ("saved", "unavailable", "missing"),
        "comments_state": ("saved", "with_comments", "missing"),
        "download_source": ("cobalt", "yt-dlp", "legacy"),
        "portable_metadata": ("embedded", "failed", "missing"),
    }
    for key, allowed in filter_values.items():
        if q[key] is not None and q[key] not in allowed:
            raise ValueError(f"unknown {key.replace('_', ' ')} filter")
    clauses, params = _item_filters(kinds=q["kinds"], statuses=q["statuses"])
    parsed = structured_search.parse(q["query"])
    fts_query = _scope_fts_match(structured_search.fts_query(parsed.terms), q["search_scope"])
    advanced_clauses, advanced_params = _advanced_search_clauses(parsed)
    filter_clauses, filter_params = _page_filter_clauses(q)
    return q, clauses + advanced_clauses + filter_clauses, params + advanced_params + filter_params, fts_query


def _page_order(q, fts_query):
    """Resolve the effective sort -> (order, order_sql, field, direction, seed)."""
    order = q["order"]
    seed = q["seed"]
    if fts_query and order == "latest":
        order = "relevance"
    if order == "random":
        if seed is None:
            raise ValueError("random order requires a shuffle seed")
        seed = int(seed) % _RANDOM_MODULUS
        return order, f"{_random_key_sql(seed)} ASC, id ASC", None, None, seed
    if order not in _PAGE_ORDERS:
        raise ValueError(f"unknown item order: {order}")
    order_sql, field, direction = _PAGE_ORDERS[order]
    return order, order_sql, field, direction, seed


def _page_sql(select, clauses, params, fts_query, search_scope="posts"):
    """SQL head (FTS CTE or plain item scan) + WHERE for one Gallery query."""
    if fts_query:
        if search_scope in ("posts", "songs"):
            sql = (
                "WITH matched AS (SELECT item.*, bm25(item_search) AS rank "
                "FROM item_search JOIN item ON item_search.rowid = item.id "
                "WHERE item_search MATCH ?) "
                f"SELECT {select} FROM matched AS item"
            )
            params = [fts_query, *params]
        elif search_scope == "comments":
            sql = (
                "WITH matched AS (SELECT item.*, bm25(comment_search) AS rank "
                "FROM comment_search JOIN item ON comment_search.rowid = item.id "
                "WHERE comment_search MATCH ?) "
                f"SELECT {select} FROM matched AS item"
            )
            params = [fts_query, *params]
        elif search_scope == "analysis":
            sql = (
                "WITH scores AS ("
                " SELECT DISTINCT analysis_segment.item_id, 0.0 AS rank"
                " FROM analysis_search JOIN analysis_segment"
                " ON analysis_search.rowid = analysis_segment.id"
                " WHERE analysis_search MATCH ?"
                "), matched AS (SELECT item.*, scores.rank FROM scores"
                " JOIN item ON item.id = scores.item_id) "
                f"SELECT {select} FROM matched AS item"
            )
            params = [fts_query, *params]
        else:
            sql = (
                "WITH hits AS ("
                " SELECT item_search.rowid AS item_id, bm25(item_search) AS rank"
                " FROM item_search WHERE item_search MATCH ?"
                " UNION ALL"
                " SELECT comment_search.rowid AS item_id, bm25(comment_search) AS rank"
                " FROM comment_search WHERE comment_search MATCH ?"
                " UNION ALL"
                " SELECT analysis_segment.item_id, 0.0 AS rank"
                " FROM analysis_search JOIN analysis_segment"
                " ON analysis_search.rowid = analysis_segment.id"
                " WHERE analysis_search MATCH ?"
                "), scores AS (SELECT item_id, MIN(rank) AS rank FROM hits GROUP BY item_id),"
                " matched AS (SELECT item.*, scores.rank FROM scores"
                " JOIN item ON item.id = scores.item_id) "
                f"SELECT {select} FROM matched AS item"
            )
            params = [fts_query, fts_query, fts_query, *params]
    else:
        sql = f"SELECT {select} FROM item"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    return sql, params


def page_items(conn, **query):
    """Return one cursor page without materializing the whole Archive library."""
    q, clauses, params, fts_query = _page_query_base(query, "page_items")
    cursor = q["cursor"]
    limit = q["limit"]
    order, order_sql, field, direction, seed = _page_order(q, fts_query)
    if cursor is not None:
        if order == "random":
            if get_item(conn, int(cursor)) is None:
                raise ValueError("unknown pagination cursor")
            key_sql = _random_key_sql(seed)
            cursor_key = _random_order_key(cursor, seed)
            clauses.append(f"({key_sql} > ? OR ({key_sql} = ? AND id > ?))")
            params += [cursor_key, cursor_key, int(cursor)]
        elif order == "audio_missing":
            cursor_row = get_item(conn, int(cursor))
            if cursor_row is None:
                raise ValueError("unknown pagination cursor")
            cursor_key = 0 if (cursor_row["has_audio"] == 0 or cursor_row["audio_silent"] == 1) else 1 if cursor_row["has_audio"] == 1 else 2
            key_sql = "CASE WHEN (has_audio = 0 OR audio_silent = 1) THEN 0 WHEN has_audio = 1 THEN 1 ELSE 2 END"
            clauses.append(f"({key_sql} > ? OR ({key_sql} = ? AND id < ?))")
            params += [cursor_key, cursor_key, int(cursor)]
        elif order == "relevance":
            cursor_sql, cursor_params = _page_sql(
                "rank", ["id = ?"], [int(cursor)], fts_query, q["search_scope"],
            )
            cursor_row = conn.execute(cursor_sql, cursor_params).fetchone()
            if cursor_row is None:
                raise ValueError("unknown pagination cursor")
            clauses.append("(rank > ? OR (rank = ? AND id < ?))")
            params += [cursor_row["rank"], cursor_row["rank"], int(cursor)]
        else:
            cursor_row = get_item(conn, int(cursor))
            if cursor_row is None:
                raise ValueError("unknown pagination cursor")
            # Every field-less order (random/audio_missing/relevance) is handled
            # above, so a plain order always carries a cursor field here.
            cursor_value = cursor_row[field]
            if cursor_value is None:
                raise ValueError("cursor cannot be used for an unindexed item")
            comparator = "<" if direction == "DESC" else ">"
            clauses.append(f"({field} {comparator} ? OR ({field} = ? AND id {comparator} ?))")
            params += [cursor_value, cursor_value, int(cursor)]
    if field is not None:
        clauses.append(f"{field} IS NOT NULL")
    sql, params = _page_sql("*", clauses, params, fts_query, q["search_scope"])
    sql += f" ORDER BY {order_sql} LIMIT ?"
    params.append(max(1, min(int(limit), 100)))
    return conn.execute(sql, params).fetchall()


def feed_ids(conn, **query):
    """Every matching item's id in the Gallery's chosen sort order, unpaged. Lets
    a filtered Gallery view open a bounded Feed of exactly those favorites."""
    q, clauses, params, fts_query = _page_query_base(query, "feed_ids")
    _order, order_sql, field, _direction, _seed = _page_order(q, fts_query)
    if field is not None:
        clauses.append(f"{field} IS NOT NULL")
    sql, params = _page_sql("id", clauses, params, fts_query, q["search_scope"])
    sql += f" ORDER BY {order_sql}"
    return [row["id"] for row in conn.execute(sql, params).fetchall()]


def window_items(conn, item_id, limit=50):
    """Return the selected Favorite then its older archive neighbors."""
    selected = get_item(conn, item_id)
    if selected is None:
        return []
    return conn.execute(
        "SELECT * FROM item WHERE favorite_order <= ? "
        "ORDER BY favorite_order DESC, id DESC LIMIT ?",
        (selected["favorite_order"], max(1, min(int(limit), 100))),
    ).fetchall()


def playable_item_ids(conn):
    return [row["id"] for row in conn.execute("SELECT id FROM item WHERE status = 'done' ORDER BY id").fetchall()]


def counts_by_status(conn):
    rows = conn.execute("SELECT status, COUNT(*) AS c FROM item GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}


# --- mounted Storage locations + verified Media placements -----------------

def list_storage_locations(conn):
    return conn.execute(
        "SELECT * FROM storage_location ORDER BY name COLLATE NOCASE, id"
    ).fetchall()


def get_storage_location(conn, location_id):
    return conn.execute(
        "SELECT * FROM storage_location WHERE id = ?", (location_id,)
    ).fetchone()


def insert_storage_location(conn, name, path, available, error=None):
    now = _now()
    cursor = conn.execute(
        "INSERT INTO storage_location "
        "(name, path, available, last_error, last_checked_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, path, 1 if available else 0, error, now, now, now),
    )
    conn.commit()
    return cursor.lastrowid


def update_storage_location(conn, location_id, **fields):
    if not fields:
        return get_storage_location(conn, location_id)
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{column} = ?" for column in fields)
    cursor = conn.execute(
        f"UPDATE storage_location SET {assignments} WHERE id = ?",
        (*fields.values(), location_id),
    )
    conn.commit()
    return get_storage_location(conn, location_id) if cursor.rowcount else None


def delete_storage_location(conn, location_id):
    try:
        cursor = conn.execute(
            "DELETE FROM storage_location WHERE id = ?", (location_id,)
        )
        conn.commit()
        return bool(cursor.rowcount)
    except sqlite3.IntegrityError:
        conn.rollback()
        return False


def record_media_placement(
    conn,
    item_id,
    location_id,
    relative_root,
    byte_count,
    manifest_digest,
    *,
    verified,
    is_active=True,
    files=None,
):
    now = _now()
    conn.execute(
        "INSERT INTO media_placement "
        "(item_id, location_id, relative_root, verified, byte_count, manifest_digest, "
        "is_active, created_at, verified_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(item_id, location_id) DO UPDATE SET "
        "relative_root = excluded.relative_root, verified = excluded.verified, "
        "byte_count = excluded.byte_count, manifest_digest = excluded.manifest_digest, "
        "is_active = excluded.is_active, verified_at = excluded.verified_at, "
        "updated_at = excluded.updated_at",
        (
            item_id, location_id, relative_root, 1 if verified else 0,
            int(byte_count), manifest_digest, 1 if is_active else 0, now,
            now if verified else None, now,
        ),
    )
    placement = conn.execute(
        "SELECT id FROM media_placement WHERE item_id = ? AND location_id = ?",
        (item_id, location_id),
    ).fetchone()
    if files is not None:
        conn.execute(
            "DELETE FROM media_placement_file WHERE placement_id = ?",
            (placement["id"],),
        )
        conn.executemany(
            "INSERT INTO media_placement_file "
            "(placement_id, path, byte_count, sha256) VALUES (?, ?, ?, ?)",
            [
                (placement["id"], entry["path"], entry["size"], entry["sha256"])
                for entry in files
            ],
        )
    conn.commit()
    return placement["id"]


def media_placements(conn, item_id=None):
    if item_id is None:
        return conn.execute(
            "SELECT * FROM media_placement ORDER BY item_id, location_id"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM media_placement WHERE item_id = ? ORDER BY location_id",
        (item_id,),
    ).fetchall()


def placement_files(conn, placement_id):
    return conn.execute(
        "SELECT path, byte_count AS size, sha256 FROM media_placement_file "
        "WHERE placement_id = ? ORDER BY path",
        (placement_id,),
    ).fetchall()


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


# Allowed control transitions: requested state -> states it may be entered from.
_CONTROL_TRANSITIONS = {
    "paused": ("running", "paused"),
    "running": ("running", "paused"),
    "stopping": ("running", "paused", "stopping"),
    # The failure heal (jobs thread) may only fail a run that is still active —
    # it must never clobber a terminal idle/stopped that execute already wrote.
    "failed": ("running", "paused", "stopping"),
}


def set_active_run_state(conn, state):
    """Change control state only while the persisted run is still active.

    A run that is stopping stays stopping: Pause/Continue must not cancel a
    user's Stop.
    """
    allowed = _CONTROL_TRANSITIONS.get(state)
    if allowed is None:
        return False
    placeholders = ",".join("?" for _ in allowed)
    cursor = conn.execute(
        f"UPDATE run_state SET state = ?, updated_at = ? WHERE id = 1 AND state IN ({placeholders})",
        (state, _now(), *allowed),
    )
    conn.commit()
    return cursor.rowcount == 1


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
        WHERE status = 'done' AND offloaded = 0 AND archive_missing = 0
        """
    ).fetchone()
    return {name: int(row[name] or 0) for name in ("total", "indexed", "pending", "failed")}


def library_statistics(conn):
    """Return lightweight Archive totals for the Sync overview."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS favorites,
            SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS ready,
            SUM(CASE WHEN kind = 'video' THEN 1 ELSE 0 END) AS videos,
            SUM(CASE WHEN kind = 'slideshow' THEN 1 ELSE 0 END) AS slideshows,
            SUM(CASE WHEN thumbnail_path IS NOT NULL THEN 1 ELSE 0 END) AS indexed,
            SUM(CASE WHEN status = 'done' AND offloaded = 0
                AND link NOT LIKE 'local://%'
                AND (has_audio = 0 OR audio_silent = 1)
                THEN 1 ELSE 0 END) AS audio_repairs,
            SUM(COALESCE(duration_s, 0)) AS duration_s,
            SUM(COALESCE(media_size, 0)) AS media_size
        FROM item
        """
    ).fetchone()
    return {
        "favorites": int(row["favorites"] or 0),
        "ready": int(row["ready"] or 0),
        "videos": int(row["videos"] or 0),
        "slideshows": int(row["slideshows"] or 0),
        "indexed": int(row["indexed"] or 0),
        "audio_repairs": int(row["audio_repairs"] or 0),
        "duration_s": float(row["duration_s"] or 0),
        "media_size": int(row["media_size"] or 0),
    }


def set_library_settings(conn, index_enabled=None, thumbnail_width=None,
                         song_id_enabled=None, portable_metadata_enabled=None):
    fields = {}
    if index_enabled is not None:
        fields["index_enabled"] = 1 if index_enabled else 0
    if thumbnail_width is not None:
        if thumbnail_width not in (320, 480):
            raise ValueError("thumbnail width must be 320 or 480")
        fields["thumbnail_width"] = thumbnail_width
    if song_id_enabled is not None:
        fields["song_id_enabled"] = 1 if song_id_enabled else 0
    if portable_metadata_enabled is not None:
        fields["portable_metadata_enabled"] = 1 if portable_metadata_enabled else 0
    if not fields:
        return
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{name} = ?" for name in fields)
    conn.execute(f"UPDATE library_settings SET {assignments} WHERE id = 1", tuple(fields.values()))
    conn.commit()


def set_default_audio(conn, name):
    """Set the custom slideshow fallback filename, or clear it with ``None``."""
    conn.execute(
        "UPDATE library_settings SET default_audio_name = ?, updated_at = ? WHERE id = 1",
        (name, _now()),
    )
    conn.commit()


# --- saved named lists -------------------------------------------------------
# One CRUD implementation for every user-named saved collection (Gallery
# presets, term lists, playback queues, song playlists). A kind maps to its
# table plus the payload fields persisted beside ``name``; adding the next
# collection is one row here (plus its schema table).

def _dump_json(value):
    return json.dumps(value, separators=(",", ":"))


def _dump_json_sorted(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


_RAW = (lambda value: value, lambda value: value)
_JSON = (_dump_json, json.loads)
_JSON_SORTED = (_dump_json_sorted, json.loads)

# kind -> (table, ((public_field, column, (encode, decode)), ...))
SAVED_LIST_KINDS = {
    "gallery_preset": ("gallery_preset", (("filters", "filters_json", _JSON_SORTED),)),
    "gallery_term_list": ("gallery_term_list", (("mode", "mode", _RAW), ("terms", "terms_json", _JSON))),
    "playback_queue": ("playback_queue", (("item_ids", "item_ids_json", _JSON),)),
    "song_playlist": ("song_playlist", (("song_ids", "song_ids_json", _JSON),)),
}


def list_saved_lists(conn, kind):
    """Every saved entry of one kind, name-ordered, payload decoded."""
    table, fields = SAVED_LIST_KINDS[kind]
    columns = ", ".join(["id", "name", *(column for _field, column, _codec in fields)])
    rows = conn.execute(f"SELECT {columns} FROM {table} ORDER BY name COLLATE NOCASE, id").fetchall()
    return [
        {"id": row["id"], "name": row["name"],
         **{field: codec[1](row[column]) for field, column, codec in fields}}
        for row in rows
    ]


def get_saved_list(conn, kind, entry_id):
    """One decoded saved entry, or ``None`` when the id does not exist."""
    table, fields = SAVED_LIST_KINDS[kind]
    columns = ", ".join(["id", "name", *(column for _field, column, _codec in fields)])
    row = conn.execute(
        f"SELECT {columns} FROM {table} WHERE id = ?", (entry_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        **{field: codec[1](row[column]) for field, column, codec in fields},
    }


def save_saved_list(conn, kind, name, payload):
    """Insert one named entry; raises ``sqlite3.IntegrityError`` on a name clash."""
    table, fields = SAVED_LIST_KINDS[kind]
    columns = ["name", *(column for _field, column, _codec in fields), "created_at"]
    values = (name, *(codec[0](payload[field]) for field, _column, codec in fields), _now())
    placeholders = ", ".join("?" for _ in columns)
    cursor = conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", values,
    )
    conn.commit()
    return cursor.lastrowid


def delete_saved_list(conn, kind, entry_id):
    table, _fields = SAVED_LIST_KINDS[kind]
    cursor = conn.execute(f"DELETE FROM {table} WHERE id = ?", (entry_id,))
    conn.commit()
    return cursor.rowcount > 0


# --- Spotify push ------------------------------------------------------------

def get_song_playlist(conn, playlist_id):
    """One saved playlist with decoded song ids, or None."""
    row = conn.execute(
        "SELECT id, name, song_ids_json, spotify_playlist_id FROM song_playlist WHERE id = ?",
        (playlist_id,),
    ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "name": row["name"],
            "song_ids": json.loads(row["song_ids_json"]),
            "spotify_playlist_id": row["spotify_playlist_id"]}


def set_song_playlist_spotify_id(conn, playlist_id, spotify_playlist_id):
    conn.execute("UPDATE song_playlist SET spotify_playlist_id = ? WHERE id = ?",
                 (spotify_playlist_id, playlist_id))
    conn.commit()


def set_song_spotify_url(conn, song_id, url):
    """Write back a search-matched track link so in-app links improve too."""
    conn.execute("UPDATE song SET spotify_url = ? WHERE id = ?", (url, song_id))
    conn.commit()


def get_spotify_auth(conn):
    """The singleton Spotify connection row (None when never connected)."""
    return conn.execute("SELECT * FROM spotify_auth WHERE id = 1").fetchone()


def save_spotify_auth(conn, **fields):
    """Merge fields into the singleton row, creating it on first use."""
    if conn.execute("SELECT 1 FROM spotify_auth WHERE id = 1").fetchone() is None:
        conn.execute("INSERT INTO spotify_auth (id, updated_at) VALUES (1, ?)", (_now(),))
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{column} = ?" for column in fields)
    conn.execute(f"UPDATE spotify_auth SET {assignments} WHERE id = 1", (*fields.values(),))
    conn.commit()


def clear_spotify_auth(conn):
    """Disconnect: delete tokens but keep the client id for easy reconnects."""
    conn.execute(
        "UPDATE spotify_auth SET access_token = NULL, refresh_token = NULL, "
        "expires_at = NULL, account_name = NULL, updated_at = ? WHERE id = 1",
        (_now(),),
    )
    conn.commit()


# --- durable Archive run history -------------------------------------------

def get_pipeline_settings(conn, kind="sync"):
    row = conn.execute(
        "SELECT kind, phases_json, updated_at FROM pipeline_setting WHERE kind = ?",
        (kind,),
    ).fetchone()
    return None if row is None else {
        "kind": row["kind"], "phases": json.loads(row["phases_json"]),
        "updated_at": row["updated_at"],
    }


def set_pipeline_settings(conn, kind, phases):
    now = _now()
    conn.execute(
        "INSERT INTO pipeline_setting(kind, phases_json, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(kind) DO UPDATE SET phases_json = excluded.phases_json, "
        "updated_at = excluded.updated_at",
        (kind, json.dumps(phases, separators=(",", ":")), now),
    )
    conn.commit()
    return get_pipeline_settings(conn, kind)


def list_run_schedules(conn):
    return [
        {**dict(row), "enabled": bool(row["enabled"])}
        for row in conn.execute("SELECT * FROM run_schedule ORDER BY name COLLATE NOCASE, id")
    ]


def get_run_schedule(conn, schedule_id):
    row = conn.execute("SELECT * FROM run_schedule WHERE id = ?", (schedule_id,)).fetchone()
    return None if row is None else {**dict(row), "enabled": bool(row["enabled"])}


def save_run_schedule(conn, values, schedule_id=None):
    now = _now()
    columns = (
        "name", "run_kind", "cadence", "local_time", "weekday",
        "timezone", "enabled", "next_due_at",
    )
    params = [values[name] for name in columns]
    params[6] = 1 if params[6] else 0
    if schedule_id is None:
        cursor = conn.execute(
            f"INSERT INTO run_schedule ({', '.join(columns)}, created_at, updated_at) "
            f"VALUES ({', '.join('?' for _ in columns)}, ?, ?)",
            (*params, now, now),
        )
        schedule_id = cursor.lastrowid
    else:
        assignments = ", ".join(f"{name} = ?" for name in columns)
        cursor = conn.execute(
            f"UPDATE run_schedule SET {assignments}, updated_at = ? WHERE id = ?",
            (*params, now, schedule_id),
        )
        if cursor.rowcount == 0:
            return None
    conn.commit()
    return get_run_schedule(conn, schedule_id)


def mark_schedule_started(conn, schedule_id, *, local_date, started_at, next_due_at):
    conn.execute(
        "UPDATE run_schedule SET last_local_date = ?, last_started_at = ?, "
        "last_outcome = 'started', next_due_at = ?, updated_at = ? WHERE id = ?",
        (local_date, started_at, next_due_at, _now(), schedule_id),
    )
    conn.commit()


def set_schedule_outcome(conn, schedule_id, outcome):
    conn.execute(
        "UPDATE run_schedule SET last_outcome = ?, updated_at = ? WHERE id = ?",
        (outcome, _now(), schedule_id),
    )
    conn.commit()


def delete_run_schedule(conn, schedule_id):
    cursor = conn.execute("DELETE FROM run_schedule WHERE id = ?", (schedule_id,))
    conn.commit()
    return cursor.rowcount > 0


# --- creator monitoring ----------------------------------------------------

def _monitor_dict(row):
    if row is None:
        return None
    result = dict(row)
    result["enabled"] = bool(result["enabled"])
    result["keywords"] = json.loads(result.pop("keywords_json", "[]"))
    result["last_seen_post_ids"] = json.loads(result.pop("last_seen_post_ids_json", "[]"))
    for field in ("exclude_reposts", "collect_comments", "analyze_new", "identify_songs"):
        result[field] = bool(result[field])
    return result


def save_creator_monitor(conn, username, interval_hours=6, enabled=True, now=None,
                         archive_mode="all", keywords=None, exclude_reposts=False,
                         max_backlog_days=None, collect_comments=True,
                         analyze_new=False, identify_songs=False,
                         seen_post_ids=None):
    from datetime import datetime, timedelta, timezone
    interval_hours = int(interval_hours)
    if not 1 <= interval_hours <= 168:
        raise ValueError("monitor interval must be between 1 and 168 hours")
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("monitor clock must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    next_check = instant + timedelta(hours=interval_hours) if enabled else None
    stamp = instant.isoformat()
    if archive_mode not in ("all", "matching"):
        raise ValueError("archive mode must be all or matching")
    keywords = [str(value).strip() for value in (keywords or []) if str(value).strip()]
    if archive_mode == "matching" and not keywords:
        raise ValueError("matching monitors need at least one keyword")
    if max_backlog_days is not None and not 1 <= int(max_backlog_days) <= 36500:
        raise ValueError("backlog days must be between 1 and 36500")
    conn.execute(
        "INSERT INTO creator_monitor "
        "(username, enabled, interval_hours, next_check_at, archive_mode, keywords_json, "
        "exclude_reposts, max_backlog_days, collect_comments, analyze_new, identify_songs, "
        "last_seen_post_ids_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(username) DO UPDATE SET "
        "enabled = excluded.enabled, interval_hours = excluded.interval_hours, "
        "archive_mode = excluded.archive_mode, keywords_json = excluded.keywords_json, "
        "exclude_reposts = excluded.exclude_reposts, max_backlog_days = excluded.max_backlog_days, "
        "collect_comments = excluded.collect_comments, analyze_new = excluded.analyze_new, "
        "identify_songs = excluded.identify_songs, "
        "last_seen_post_ids_json = CASE WHEN ? THEN excluded.last_seen_post_ids_json ELSE creator_monitor.last_seen_post_ids_json END, "
        "next_check_at = excluded.next_check_at, updated_at = excluded.updated_at",
        (username, 1 if enabled else 0, interval_hours,
         next_check.isoformat() if next_check else None,
         archive_mode, json.dumps(keywords, separators=(",", ":")),
         1 if exclude_reposts else 0, int(max_backlog_days) if max_backlog_days is not None else None,
         1 if collect_comments else 0, 1 if analyze_new else 0, 1 if identify_songs else 0,
         json.dumps(seen_post_ids or [], separators=(",", ":")), stamp, stamp,
         1 if seen_post_ids is not None else 0),
    )
    conn.commit()
    return _monitor_dict(conn.execute(
        "SELECT * FROM creator_monitor WHERE username = ?", (username,),
    ).fetchone())


def list_creator_monitors(conn):
    return [_monitor_dict(row) for row in conn.execute(
        "SELECT * FROM creator_monitor ORDER BY username COLLATE NOCASE"
    ).fetchall()]


def get_creator_monitor(conn, monitor_id):
    return _monitor_dict(conn.execute(
        "SELECT * FROM creator_monitor WHERE id = ?", (int(monitor_id),),
    ).fetchone())


def due_creator_monitors(conn, now):
    return [_monitor_dict(row) for row in conn.execute(
        "SELECT * FROM creator_monitor WHERE enabled = 1 "
        "AND (next_check_at IS NULL OR next_check_at <= ?) ORDER BY next_check_at, id",
        (now.isoformat(),),
    ).fetchall()]


def update_creator_monitor(conn, monitor_id, *, enabled=None, interval_hours=None, now=None,
                           archive_mode=None, keywords=None, exclude_reposts=None,
                           max_backlog_days="unchanged", collect_comments=None,
                           analyze_new=None, identify_songs=None):
    current = get_creator_monitor(conn, monitor_id)
    if current is None:
        return None
    return save_creator_monitor(
        conn, current["username"],
        current["interval_hours"] if interval_hours is None else interval_hours,
        current["enabled"] if enabled is None else enabled,
        now=now,
        archive_mode=current["archive_mode"] if archive_mode is None else archive_mode,
        keywords=current["keywords"] if keywords is None else keywords,
        exclude_reposts=current["exclude_reposts"] if exclude_reposts is None else exclude_reposts,
        max_backlog_days=current["max_backlog_days"] if max_backlog_days == "unchanged" else max_backlog_days,
        collect_comments=current["collect_comments"] if collect_comments is None else collect_comments,
        analyze_new=current["analyze_new"] if analyze_new is None else analyze_new,
        identify_songs=current["identify_songs"] if identify_songs is None else identify_songs,
    )


def mark_creator_monitor_checked(conn, monitor_id, *, added, error, now,
                                 changed=0, missing=0, seen_post_ids=None):
    from datetime import timedelta
    current = get_creator_monitor(conn, monitor_id)
    if current is None:
        return None
    next_check = now + timedelta(hours=current["interval_hours"])
    conn.execute(
        "UPDATE creator_monitor SET last_checked_at = ?, last_new_count = ?, "
        "last_error = ?, last_changed_count = ?, last_missing_count = ?, "
        "last_seen_post_ids_json = COALESCE(?, last_seen_post_ids_json), "
        "next_check_at = ?, updated_at = ? WHERE id = ?",
        (now.isoformat(), int(added), str(error) if error else None,
         int(changed), int(missing),
         json.dumps(seen_post_ids, separators=(",", ":")) if seen_post_ids is not None else None,
         next_check.isoformat(), now.isoformat(), int(monitor_id)),
    )
    conn.commit()
    return get_creator_monitor(conn, monitor_id)


def check_creator_monitor_now(conn, monitor_id, now=None):
    from datetime import datetime, timezone
    if get_creator_monitor(conn, monitor_id) is None:
        return False
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    conn.execute(
        "UPDATE creator_monitor SET next_check_at = ?, updated_at = ? WHERE id = ?",
        (instant.isoformat(), instant.isoformat(), int(monitor_id)),
    )
    conn.commit()
    return True


def delete_creator_monitor(conn, monitor_id):
    cursor = conn.execute(
        "DELETE FROM creator_monitor WHERE id = ?", (int(monitor_id),),
    )
    conn.commit()
    return cursor.rowcount > 0


_UNSAFE_RUN_PARAM = object()


def _safe_run_params(params):
    """Drop injected functions/objects; keep only replayable JSON values."""
    def clean(value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [
                cleaned for item in value
                if (cleaned := clean(item)) is not _UNSAFE_RUN_PARAM
            ]
        if isinstance(value, dict):
            return {
                key: cleaned for key, item in value.items()
                if isinstance(key, str)
                and (cleaned := clean(item)) is not _UNSAFE_RUN_PARAM
            }
        return _UNSAFE_RUN_PARAM

    return {
        key: cleaned for key, value in (params or {}).items()
        if isinstance(key, str)
        and (cleaned := clean(value)) is not _UNSAFE_RUN_PARAM
    }


def start_run_history(conn, kind, *, retry_of=None, params=None):
    cursor = conn.execute(
        "INSERT INTO run_history (kind, started_at, retry_of, params_json) VALUES (?, ?, ?, ?)",
        (
            kind, _now(), retry_of,
            json.dumps(_safe_run_params(params), separators=(",", ":"), sort_keys=True),
        ),
    )
    conn.commit()
    return cursor.lastrowid


def set_run_history_context(conn, run_id, pipeline_id, parent_kind, phase, phase_index):
    conn.execute(
        "UPDATE run_history SET pipeline_id = ?, parent_kind = ?, phase = ?, phase_index = ? "
        "WHERE id = ?",
        (pipeline_id, parent_kind, phase, phase_index, run_id),
    )
    conn.commit()


def finish_run_history(conn, run_id, outcome, counts, error=None):
    conn.execute(
        "UPDATE run_history SET outcome = ?, finished_at = ?, counts_json = ?, error = ? WHERE id = ?",
        (outcome, _now(), json.dumps(counts, separators=(",", ":"), sort_keys=True), error, run_id),
    )
    conn.commit()


def list_run_history(conn, limit=20):
    rows = conn.execute(
        "SELECT id, kind, pipeline_id, parent_kind, phase, phase_index, "
        "outcome, started_at, finished_at, counts_json, retry_of, params_json, error "
        "FROM run_history ORDER BY id DESC LIMIT ?",
        (max(1, min(int(limit), 100)),),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "pipeline_id": row["pipeline_id"],
            "parent_kind": row["parent_kind"] or row["kind"],
            "phase": row["phase"] or row["kind"],
            "phase_index": row["phase_index"],
            "outcome": row["outcome"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "counts": json.loads(row["counts_json"] or "{}"),
            "retry_of": row["retry_of"],
            "params": json.loads(row["params_json"] or "{}"),
            "error": row["error"],
        }
        for row in rows
    ]


def get_run_history(conn, run_id):
    row = conn.execute(
        "SELECT id, kind, pipeline_id, parent_kind, phase, phase_index, outcome, "
        "started_at, finished_at, counts_json, retry_of, params_json, error "
        "FROM run_history WHERE id = ?", (run_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"], "kind": row["kind"],
        "pipeline_id": row["pipeline_id"],
        "parent_kind": row["parent_kind"] or row["kind"],
        "phase": row["phase"] or row["kind"],
        "phase_index": row["phase_index"], "outcome": row["outcome"],
        "started_at": row["started_at"], "finished_at": row["finished_at"],
        "counts": json.loads(row["counts_json"] or "{}"),
        "retry_of": row["retry_of"],
        "params": json.loads(row["params_json"] or "{}"),
        "error": row["error"],
    }
