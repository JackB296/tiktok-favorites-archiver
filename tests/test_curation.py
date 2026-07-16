"""Tests for core.curation — bulk marks, selector resolution, requeueing (stdlib)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import curation, store


def _db():
    return store.init_db(store.connect(":memory:"))


def test_requeue_selected_only_repairs_failed_or_missing_remote_items():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/failed", status="failed")
    store.insert_item(conn, 2, "https://tiktok.com/missing", status="done")
    store.insert_item(conn, 3, "https://tiktok.com/present", status="done")
    store.insert_item(conn, 4, "local://file/4", status="failed")
    store.insert_item(conn, 5, "https://tiktok.com/pending", status="pending")
    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "3.mp4"), "w").close()
        result = curation.requeue_selected(conn, dl, [1, 2, 3, 4, 5, 999])
    assert result == {"requeued": [1, 2], "skipped": 4}
    assert store.get_item(conn, 1)["status"] == "pending"
    assert store.get_item(conn, 2)["status"] == "pending"
    assert store.get_item(conn, 3)["status"] == "done"
    assert store.get_item(conn, 4)["status"] == "failed"
    assert store.get_item(conn, 5)["status"] == "pending"


def test_requeue_selected_skips_offloaded_items():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", status="done")  # offloaded -> skip
    store.insert_item(conn, 2, "https://tiktok.com/b", status="failed")
    store.set_offloaded(conn, [1])

    with tempfile.TemporaryDirectory() as dl:
        result = curation.requeue_selected(conn, dl, [1, 2])

    assert result == {"requeued": [2], "skipped": 1}
    assert store.get_item(conn, 1)["status"] == "done"
    assert store.get_item(conn, 2)["status"] == "pending"


def test_unoffload_requeues_only_cleared_items_without_a_local_file():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", status="pending")  # marked, no file -> pending again
    store.insert_item(conn, 2, "https://tiktok.com/b", status="done")     # marked, file present -> stays done
    store.insert_item(conn, 3, "https://tiktok.com/c", status="failed")   # never marked -> untouched
    store.insert_item(conn, 4, "local://4.mp4", status="done")            # marked, synthetic -> stays done
    store.set_offloaded(conn, [1, 2, 4])

    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "2.mp4"), "w").close()
        result = curation.unoffload_items(conn, dl, [1, 2, 3, 4])

    assert result == {"changed": 3, "requeued": 1}
    assert store.get_item(conn, 1)["status"] == "pending"
    assert store.get_item(conn, 2)["status"] == "done"
    assert store.get_item(conn, 3)["status"] == "failed"
    assert store.get_item(conn, 4)["status"] == "done"
    for item_id in (1, 2, 4):
        assert store.get_item(conn, item_id)["offloaded"] == 0


def test_unoffload_of_unmarked_items_changes_nothing():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", status="failed")

    with tempfile.TemporaryDirectory() as dl:
        result = curation.unoffload_items(conn, dl, [1])

    assert result == {"changed": 0, "requeued": 0}
    assert store.get_item(conn, 1)["status"] == "failed"


def test_mark_offload_by_explicit_ids():
    conn = _db()
    for n in (1, 2, 3):
        store.insert_item(conn, n, f"https://tiktok.com/{n}", status="done")

    with tempfile.TemporaryDirectory() as dl:
        result = curation.mark(conn, dl, "offload", "ids", [1, 3])

    assert result == {"matched": 2, "changed": 2}
    assert store.get_item(conn, 1)["offloaded"] == 1
    assert store.get_item(conn, 2)["offloaded"] == 0
    assert store.get_item(conn, 3)["offloaded"] == 1


def test_mark_by_range_resolves_archive_numbers():
    conn = _db()
    for n in (1, 2, 3, 5):
        store.insert_item(conn, n, f"https://tiktok.com/{n}", status="pending")

    with tempfile.TemporaryDirectory() as dl:
        result = curation.mark(conn, dl, "ignore", "range", {"first_id": 2, "last_id": 5})

    assert result == {"matched": 3, "changed": 3}
    assert store.get_item(conn, 1)["status"] == "pending"
    for n in (2, 3, 5):
        assert store.get_item(conn, n)["status"] == "ignored"


def test_mark_by_filter_uses_the_gallery_query_vocabulary():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", status="failed")
    store.insert_item(conn, 2, "https://tiktok.com/b", status="pending")

    with tempfile.TemporaryDirectory() as dl:
        result = curation.mark(conn, dl, "ignore", "filter", {"statuses": ["failed"]})

    assert result == {"matched": 1, "changed": 1}
    assert store.get_item(conn, 1)["status"] == "ignored"
    assert store.get_item(conn, 2)["status"] == "pending"


def test_mark_dry_run_counts_without_changing_anything():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", status="done")

    with tempfile.TemporaryDirectory() as dl:
        result = curation.mark(conn, dl, "offload", "ids", [1], dry_run=True)

    assert result == {"matched": 1, "changed": 0, "dry_run": True}
    assert store.get_item(conn, 1)["offloaded"] == 0


def test_mark_unoffload_reports_matched_changed_and_requeued():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", status="done")  # marked, no file
    store.set_offloaded(conn, [1])

    with tempfile.TemporaryDirectory() as dl:
        result = curation.mark(conn, dl, "unoffload", "ids", [1])

    assert result == {"matched": 1, "changed": 1, "requeued": 1}
    assert store.get_item(conn, 1)["offloaded"] == 0
    assert store.get_item(conn, 1)["status"] == "pending"


def test_mark_unignore_returns_items_to_pending():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", status="pending")

    with tempfile.TemporaryDirectory() as dl:
        curation.mark(conn, dl, "ignore", "ids", [1])
        assert store.get_item(conn, 1)["status"] == "ignored"
        curation.mark(conn, dl, "unignore", "ids", [1])

    assert store.get_item(conn, 1)["status"] == "pending"


def test_mark_rejects_an_unknown_action():
    conn = _db()
    with tempfile.TemporaryDirectory() as dl:
        try:
            curation.mark(conn, dl, "vanish", "ids", [1])
        except ValueError:
            pass
        else:
            raise AssertionError("unknown action must be rejected")


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
