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
