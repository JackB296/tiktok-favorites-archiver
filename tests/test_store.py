"""Tests for core.store — SQLite schema + CRUD + run control (stdlib sqlite3)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store


def _db():
    conn = store.connect(":memory:")
    return store.init_db(conn)


def test_init_is_idempotent_and_seeds_run_state():
    conn = _db()
    store.init_db(conn)  # second call must not error or duplicate
    rs = store.get_run_state(conn)
    assert rs["state"] == "idle" and rs["concurrency"] == store.DEFAULT_CONCURRENCY


def test_insert_and_get_item():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", favorited_at="2021-01-01")
    row = store.get_item(conn, 1)
    assert row["id"] == 1 and row["link"] == "https://tiktok.com/a"
    assert row["status"] == "pending" and row["kind"] == "unknown" and row["has_assets"] == 0
    assert store.get_item_by_link(conn, "https://tiktok.com/a")["id"] == 1


def test_next_id_preserves_gaps():
    conn = _db()
    for n, link in ((1, "a"), (2, "b"), (5, "e")):
        store.insert_item(conn, n, link)
    assert store.next_item_id(conn) == 6  # max + 1, gaps preserved


def test_upsert_link_dedups_and_numbers():
    conn = _db()
    first = store.upsert_link(conn, "a", favorited_at="2020")
    again = store.upsert_link(conn, "a")               # same link -> same id
    second = store.upsert_link(conn, "b")              # new link -> next number
    assert first == 1 and again == 1 and second == 2
    assert store.counts_by_status(conn) == {"pending": 2}


def test_status_kind_assets_metadata_transitions():
    conn = _db()
    store.insert_item(conn, 1, "a")
    store.set_status(conn, 1, "downloading")
    store.set_kind(conn, 1, "slideshow")
    store.set_has_assets(conn, 1, True)
    store.set_metadata(conn, 1, caption="hi #cats", author="someone")
    row = store.get_item(conn, 1)
    assert row["status"] == "downloading" and row["kind"] == "slideshow"
    assert row["has_assets"] == 1 and row["caption"] == "hi #cats" and row["author"] == "someone"
    store.set_status(conn, 1, "failed", error="boom")
    assert store.get_item(conn, 1)["error"] == "boom"


def test_record_work_outcome_updates_lifecycle_fields_together():
    conn = _db()
    store.insert_item(conn, 1, "a")

    store.record_work_outcome(
        conn,
        1,
        {"status": "done", "kind": "slideshow", "has_assets": 1},
    )

    row = store.get_item(conn, 1)
    assert row["status"] == "done"
    assert row["kind"] == "slideshow"
    assert row["has_assets"] == 1
    assert row["error"] is None


def test_record_asset_recovery_keeps_download_status():
    conn = _db()
    store.insert_item(conn, 1, "a", status="done")

    store.record_asset_recovery(conn, 1, {"kind": "slideshow", "has_assets": 1})

    row = store.get_item(conn, 1)
    assert row["status"] == "done"
    assert row["kind"] == "slideshow"
    assert row["has_assets"] == 1


def test_media_index_is_persisted_and_queryable():
    conn = _db()
    store.insert_item(conn, 1, "a", status="done")

    store.record_media_index(
        conn,
        1,
        {"duration_s": 42.5, "width": 1080, "height": 1920, "codec": "h264", "file_size": 123, "thumbnail_path": ".archive/thumbnails/1.webp"},
        fingerprint="123:1000",
    )

    row = store.get_item(conn, 1)
    assert row["duration_s"] == 42.5
    assert row["thumbnail_path"] == ".archive/thumbnails/1.webp"
    assert [item["id"] for item in store.items_needing_index(conn)] == []


def test_items_by_status_ordered():
    conn = _db()
    for n in (3, 1, 2):
        store.insert_item(conn, n, f"link{n}")
    store.set_status(conn, 2, "done")
    pending = store.items_by_status(conn, ["pending"])
    assert [r["id"] for r in pending] == [1, 3]  # ordered by id, excludes done


def test_run_state_updates():
    conn = _db()
    store.set_run_state(conn, state="running", phase="sync", concurrency=8, cobalt_url="http://cobalt:9000/")
    rs = store.get_run_state(conn)
    assert rs["state"] == "running" and rs["phase"] == "sync"
    assert rs["concurrency"] == 8 and rs["cobalt_url"] == "http://cobalt:9000/"


def test_search_items():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", kind="video", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/b", kind="slideshow", status="pending")
    store.set_metadata(conn, 1, "cats are great #cats", "alice")
    store.set_metadata(conn, 2, "dogs everywhere #dogs", "bob")
    assert [r["id"] for r in store.search_items(conn, query="cats")] == [1]
    assert [r["id"] for r in store.search_items(conn, query="#dogs")] == [2]
    assert [r["id"] for r in store.search_items(conn, query="alice")] == [1]        # author match
    assert [r["id"] for r in store.search_items(conn, kinds=["slideshow"])] == [2]
    assert [r["id"] for r in store.search_items(conn, statuses=["done"])] == [1]
    assert [r["id"] for r in store.search_items(conn)] == [1, 2]                     # no filter


def test_page_items_returns_latest_first_with_a_cursor():
    conn = _db()
    for item_id in range(1, 6):
        store.insert_item(conn, item_id, f"link{item_id}", status="done")

    first = store.page_items(conn, limit=2, order="latest")
    second = store.page_items(conn, limit=2, order="latest", cursor=first[-1]["id"])

    assert [row["id"] for row in first] == [5, 4]
    assert [row["id"] for row in second] == [3, 2]


def test_window_items_centers_a_favorite_with_older_neighbors():
    conn = _db()
    for item_id in range(1, 8):
        store.insert_item(conn, item_id, f"link{item_id}", status="done")

    rows = store.window_items(conn, 5, limit=3)

    assert [row["id"] for row in rows] == [5, 4, 3]


def test_playable_item_ids_return_finished_media_only():
    conn = _db()
    store.insert_item(conn, 1, "a", status="done")
    store.insert_item(conn, 2, "b", status="pending")

    assert store.playable_item_ids(conn) == [1]


def test_page_items_filters_duration_and_sorts_by_size():
    conn = _db()
    for item_id, size, duration in ((1, 10, 30), (2, 30, 10), (3, 20, 20)):
        store.insert_item(conn, item_id, f"link{item_id}", status="done")
        store.record_media_index(conn, item_id, {"thumbnail_path": "x", "duration_s": duration, "width": 1, "height": 1, "codec": "h264", "file_size": size}, "x")

    rows = store.page_items(conn, min_duration=15, order="size_desc")

    assert [row["id"] for row in rows] == [3, 1]


def test_library_index_settings_default_to_high_enabled():
    conn = _db()

    settings = store.get_library_settings(conn)

    assert settings["index_enabled"] == 1
    assert settings["thumbnail_width"] == 480


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
