"""Tests for the song-identification store layer (schema, migration, writers)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store


def _columns(conn, table="item"):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _done_audio_item(conn, url, has_audio=1):
    """A finished, local, audio-bearing favorite — the identifiable case."""
    item_id = store.upsert_link(conn, url)
    store.set_status(conn, item_id, "done")
    conn.execute("UPDATE item SET has_audio = ? WHERE id = ?", (has_audio, item_id))
    conn.commit()
    return item_id


def test_fresh_db_has_song_table_and_item_columns():
    conn = store.init_db(store.connect(":memory:"))
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "song" in tables
    assert {"song_id", "song_status", "song_source", "song_identified_at", "song_error"} <= _columns(conn)


def test_migration_adds_song_columns_to_a_legacy_db():
    """A DB created before this feature gains the song columns via init_db's
    ALTER path, and its finished audio items become identifiable."""
    # An item table shaped like a prior release (before the song columns), with
    # the columns the existing indexes and FTS triggers reference.
    conn = store.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE item (
            id INTEGER PRIMARY KEY,
            link TEXT NOT NULL UNIQUE,
            caption TEXT,
            author TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            media_size INTEGER,
            duration_s REAL,
            favorited_at TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_attempt_at TEXT,
            has_audio INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO item (id, link, status, has_audio, created_at, updated_at) "
        "VALUES (1, 'https://tiktok.com/legacy', 'done', 1, '2020-01-01', '2020-01-01')"
    )
    conn.commit()

    store.init_db(conn)

    assert {"song_id", "song_status", "song_source", "song_identified_at", "song_error"} <= _columns(conn)
    assert [row["id"] for row in store.items_needing_identification(conn)] == [1]


def test_upsert_song_dedupes_on_key():
    conn = store.init_db(store.connect(":memory:"))
    first = store.upsert_song(conn, "shazam:99", "Track", artist="Artist",
                              spotify_url="https://open.spotify.com/track/x", shazam_key="99")
    again = store.upsert_song(conn, "shazam:99", "Track", artist="Artist")
    assert first == again
    assert conn.execute("SELECT COUNT(*) FROM song").fetchone()[0] == 1
    row = store.get_song(conn, first)
    assert row["title"] == "Track"
    assert row["artist"] == "Artist"
    assert row["spotify_url"].endswith("/x")


def test_set_item_song_marks_identified():
    conn = store.init_db(store.connect(":memory:"))
    item_id = _done_audio_item(conn, "https://tiktok.com/a")
    song_id = store.upsert_song(conn, "ta:song|artist", "Song", artist="Artist")

    store.set_item_song(conn, item_id, song_id, source="auto")

    row = store.get_item(conn, item_id)
    assert row["song_id"] == song_id
    assert row["song_status"] == "identified"
    assert row["song_source"] == "auto"
    assert row["song_identified_at"] is not None
    assert row["song_error"] is None


def test_no_match_and_error_transitions():
    conn = store.init_db(store.connect(":memory:"))
    a = _done_audio_item(conn, "https://tiktok.com/a")
    b = _done_audio_item(conn, "https://tiktok.com/b")

    store.set_item_song_no_match(conn, a)
    assert store.get_item(conn, a)["song_status"] == "no_match"
    assert store.get_item(conn, a)["song_id"] is None

    store.set_item_song_error(conn, b, "network down")
    assert store.get_item(conn, b)["song_status"] == "error"
    assert store.get_item(conn, b)["song_error"] == "network down"


def test_items_needing_identification_selects_and_skips():
    conn = store.init_db(store.connect(":memory:"))
    fresh = _done_audio_item(conn, "https://tiktok.com/fresh")          # NULL -> needs
    identified = _done_audio_item(conn, "https://tiktok.com/identified")
    no_match = _done_audio_item(conn, "https://tiktok.com/nomatch")
    errored = _done_audio_item(conn, "https://tiktok.com/error")
    silent = _done_audio_item(conn, "https://tiktok.com/silent", has_audio=0)
    pending = store.upsert_link(conn, "https://tiktok.com/pending")     # not done

    song_id = store.upsert_song(conn, "shazam:1", "S", artist="A")
    store.set_item_song(conn, identified, song_id)
    store.set_item_song_no_match(conn, no_match)
    store.set_item_song_error(conn, errored, "boom")

    # Default: fresh + errored (errors always retried); skip identified, no_match, silent, pending.
    ids = [row["id"] for row in store.items_needing_identification(conn)]
    assert ids == [fresh, errored]

    # With retry_no_match, the remembered no-match is retried too.
    ids = [row["id"] for row in store.items_needing_identification(conn, retry_no_match=True)]
    assert ids == [fresh, no_match, errored]

    # Offloaded finished items are skipped (media not local).
    store.set_offloaded(conn, [fresh], True)
    ids = [row["id"] for row in store.items_needing_identification(conn)]
    assert fresh not in ids


def test_distinct_songs_counts_uses_and_lists_favorites():
    conn = store.init_db(store.connect(":memory:"))
    a = _done_audio_item(conn, "https://tiktok.com/a")
    b = _done_audio_item(conn, "https://tiktok.com/b")
    c = _done_audio_item(conn, "https://tiktok.com/c")
    viral = store.upsert_song(conn, "shazam:viral", "Viral", artist="A")
    rare = store.upsert_song(conn, "shazam:rare", "Rare", artist="B")
    store.set_item_song(conn, a, viral)
    store.set_item_song(conn, b, viral)
    store.set_item_song(conn, c, rare)

    songs = store.distinct_songs(conn)
    assert [(s["title"], s["uses"]) for s in songs] == [("Viral", 2), ("Rare", 1)]  # most-used first
    assert songs[0]["item_ids"] == [a, b]
    assert songs[1]["item_ids"] == [c]

    # item_cap bounds how many favorite ids each song carries.
    assert store.distinct_songs(conn, item_cap=1)[0]["item_ids"] == [a]


def test_song_playlist_crud():
    conn = store.init_db(store.connect(":memory:"))
    one = store.upsert_song(conn, "shazam:1", "One")
    two = store.upsert_song(conn, "shazam:2", "Two")

    pid = store.save_saved_list(conn, "song_playlist", "Favorites", {"song_ids": [one, two]})
    listed = store.list_saved_lists(conn, "song_playlist")
    assert listed == [{"id": pid, "name": "Favorites", "song_ids": [one, two]}]

    assert store.delete_saved_list(conn, "song_playlist", pid) is True
    assert store.list_saved_lists(conn, "song_playlist") == []
    assert store.delete_saved_list(conn, "song_playlist", pid) is False


def test_library_settings_opt_in_off_by_default_and_migrates():
    # Fresh DB: identification is opt-in, so off.
    conn = store.init_db(store.connect(":memory:"))
    assert store.get_library_settings(conn)["song_id_enabled"] == 0

    # A pre-feature settings table gains the column, still defaulting to off.
    legacy = store.connect(":memory:")
    legacy.executescript(
        """
        CREATE TABLE library_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            index_enabled INTEGER NOT NULL DEFAULT 1,
            thumbnail_width INTEGER NOT NULL DEFAULT 480,
            updated_at TEXT NOT NULL
        );
        INSERT INTO library_settings (id, index_enabled, thumbnail_width, updated_at)
        VALUES (1, 1, 480, '2020-01-01');
        """
    )
    legacy.commit()
    store.init_db(legacy)
    assert store.get_library_settings(legacy)["song_id_enabled"] == 0


def test_song_id_opt_in_toggles():
    conn = store.init_db(store.connect(":memory:"))
    store.set_library_settings(conn, song_id_enabled=True)
    assert store.get_library_settings(conn)["song_id_enabled"] == 1
    store.set_library_settings(conn, song_id_enabled=False)
    assert store.get_library_settings(conn)["song_id_enabled"] == 0
    # Leaving it unset does not disturb the stored value.
    store.set_library_settings(conn, thumbnail_width=320)
    assert store.get_library_settings(conn)["song_id_enabled"] == 0


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failures += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failures else 0)
