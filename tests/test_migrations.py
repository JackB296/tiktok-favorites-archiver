"""Additive schema-version and resumable-backfill bookkeeping tests."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import migrations, store


LEGACY_SCHEMA = """
CREATE TABLE item (
    id INTEGER PRIMARY KEY,
    link TEXT NOT NULL UNIQUE,
    favorited_at TEXT,
    kind TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL DEFAULT 'pending',
    has_assets INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    caption TEXT,
    author TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
INSERT INTO item (id, link, created_at, updated_at)
VALUES (7, 'https://www.tiktok.com/@old/video/7', '2020', '2020');
"""


def _schema(conn):
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
    ]


def test_current_and_legacy_databases_gain_a_durable_schema_version():
    current = store.init_db(store.connect(":memory:"))
    assert migrations.schema_version(current) == migrations.CURRENT_SCHEMA_VERSION

    legacy = store.connect(":memory:")
    legacy.executescript(LEGACY_SCHEMA)
    store.init_db(legacy)
    assert migrations.schema_version(legacy) == migrations.CURRENT_SCHEMA_VERSION
    assert store.get_item(legacy, 7)["link"].endswith("/video/7")


def test_backfill_progress_survives_connections_and_terminal_states():
    conn = store.init_db(store.connect(":memory:"))
    migrations.ensure_backfill(conn, "discovery-identities", total=100)
    assert migrations.get_backfill(conn, "discovery-identities")["status"] == "pending"

    migrations.start_backfill(conn, "discovery-identities")
    migrations.update_backfill(
        conn, "discovery-identities", cursor="item:40", processed=40, total=101,
    )
    running = migrations.get_backfill(conn, "discovery-identities")
    assert running["status"] == "running"
    assert running["cursor"] == "item:40"
    assert running["processed"] == 40
    assert running["total"] == 101

    migrations.fail_backfill(conn, "discovery-identities", "temporary failure")
    failed = migrations.get_backfill(conn, "discovery-identities")
    assert failed["status"] == "pending"
    assert failed["error"] == "temporary failure"
    assert failed["cursor"] == "item:40"

    migrations.start_backfill(conn, "discovery-identities")
    migrations.complete_backfill(conn, "discovery-identities")
    completed = migrations.get_backfill(conn, "discovery-identities")
    assert completed["status"] == "completed"
    assert completed["processed"] == completed["total"] == 101
    assert completed["error"] is None


def test_initialization_twice_preserves_schema_and_backfill_state():
    conn = store.init_db(store.connect(":memory:"))
    migrations.ensure_backfill(conn, "kept", total=9)
    migrations.start_backfill(conn, "kept")
    migrations.update_backfill(conn, "kept", cursor="8", processed=8)
    schema_before = _schema(conn)
    state_before = dict(migrations.get_backfill(conn, "kept"))

    store.init_db(conn)

    assert _schema(conn) == schema_before
    assert dict(migrations.get_backfill(conn, "kept")) == state_before


def test_archive_intelligence_tables_are_additive_and_idempotent():
    expected = {
        "analysis_segment", "analysis_search", "item_play",
        "import_history", "import_membership", "story",
    }

    current = store.init_db(store.connect(":memory:"))
    current_tables = {
        row["name"] for row in current.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }
    assert expected <= current_tables

    legacy = store.connect(":memory:")
    legacy.executescript(LEGACY_SCHEMA)
    store.init_db(legacy)
    store.init_db(legacy)
    legacy_tables = {
        row["name"] for row in legacy.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }
    assert expected <= legacy_tables
    assert store.get_item(legacy, 7)["link"].endswith("/video/7")


def test_analysis_search_index_tracks_segment_changes():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://www.tiktok.com/@cook/video/1")
    conn.execute(
        "INSERT INTO analysis_segment "
        "(item_id, source, text, start_s, end_s, created_at) "
        "VALUES (1, 'transcript', 'crispy potatoes', 4, 7, 'now')"
    )
    segment_id = conn.execute(
        "SELECT id FROM analysis_segment WHERE item_id = 1"
    ).fetchone()["id"]
    assert conn.execute(
        "SELECT rowid FROM analysis_search WHERE analysis_search MATCH 'crispy'"
    ).fetchone()["rowid"] == segment_id

    conn.execute("DELETE FROM analysis_segment WHERE id = ?", (segment_id,))
    assert conn.execute(
        "SELECT rowid FROM analysis_search WHERE analysis_search MATCH 'crispy'"
    ).fetchone() is None


def test_existing_analysis_segments_upgrade_as_manual_source_state():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://www.tiktok.com/@cook/video/1")
    conn.execute("DROP TABLE IF EXISTS analysis_source_state")
    conn.execute(
        "INSERT INTO analysis_segment "
        "(item_id, source, text, start_s, end_s, created_at) "
        "VALUES (1, 'transcript', 'keep this imported text', 4, 7, '2026-01-01')"
    )
    conn.commit()

    store.init_db(conn)

    state = conn.execute(
        "SELECT * FROM analysis_source_state "
        "WHERE item_id = 1 AND source = 'transcript'"
    ).fetchone()
    assert state["origin"] == "manual"
    assert state["status"] == "completed"
    assert state["media_fingerprint"] is None
    assert conn.execute(
        "SELECT text FROM analysis_segment WHERE item_id = 1"
    ).fetchone()["text"] == "keep this imported text"


def test_existing_sync_pipeline_gains_analysis_once_and_respects_later_removal():
    legacy = store.connect(":memory:")
    legacy.executescript(LEGACY_SCHEMA + """
        CREATE TABLE library_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            index_enabled INTEGER NOT NULL DEFAULT 1,
            thumbnail_width INTEGER NOT NULL DEFAULT 480,
            updated_at TEXT NOT NULL
        );
        INSERT INTO library_settings
        (id, index_enabled, thumbnail_width, updated_at)
        VALUES (1, 1, 480, '2026-01-01');
        CREATE TABLE pipeline_setting (
            kind TEXT PRIMARY KEY,
            phases_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO pipeline_setting(kind, phases_json, updated_at)
        VALUES ('sync', '["sync","enrich","identify"]', '2026-01-01');
    """)

    store.init_db(legacy)
    assert store.get_pipeline_settings(legacy)["phases"] == [
        "sync", "enrich", "identify", "analyze",
    ]

    store.set_pipeline_settings(legacy, "sync", ["sync", "enrich"])
    store.init_db(legacy)
    assert store.get_pipeline_settings(legacy)["phases"] == ["sync", "enrich"]


if __name__ == "__main__":
    import traceback

    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception:
            failures += 1
            print(f"FAIL {test.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failures else 0)
