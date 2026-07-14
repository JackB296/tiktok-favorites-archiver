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
