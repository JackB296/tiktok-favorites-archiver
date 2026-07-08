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
