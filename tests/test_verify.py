"""Tests for core.verify — archive integrity report and requeue (stdlib)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store, verify


def _db():
    return store.init_db(store.connect(":memory:"))


def test_clean_archive_reports_ok():
    conn = _db()
    store.insert_item(conn, 1, "a", status="done")
    store.insert_item(conn, 2, "b")  # pending needs no file
    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "1.mp4"), "w").close()
        report = verify.verify_archive(conn, dl)
    assert report["ok"] is True
    assert report["favorites"] == 2 and report["done"] == 1
    assert report["missing"]["count"] == 0
    assert report["orphans"]["count"] == 0
    assert report["leftovers"]["count"] == 0


def test_report_finds_missing_orphans_and_leftovers():
    conn = _db()
    store.insert_item(conn, 1, "a", status="done")   # file missing
    store.insert_item(conn, 2, "b", status="done")   # file present
    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "2.mp4"), "w").close()
        open(os.path.join(dl, "9.mp4"), "w").close()          # orphan
        open(os.path.join(dl, "3.mp4.part"), "w").close()     # crashed download
        open(os.path.join(dl, "4.mp4.part.mp4"), "w").close()  # crashed encode
        report = verify.verify_archive(conn, dl)
    assert report["ok"] is False
    assert report["missing"] == {"count": 1, "examples": [1]}
    assert report["orphans"] == {"count": 1, "examples": ["9.mp4"]}
    assert report["leftovers"]["count"] == 2


def test_requeue_resets_missing_done_items_but_skips_local_placeholders():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", status="done")  # missing → requeue
    store.insert_item(conn, 2, "https://tiktok.com/b", status="done")  # present → keep
    store.insert_item(conn, 3, "local://file/3", status="done")        # missing but local → skip
    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "2.mp4"), "w").close()
        result = verify.requeue_missing(conn, dl)
    assert result == {"requeued": 1}
    assert store.get_item(conn, 1)["status"] == "pending"
    assert store.get_item(conn, 2)["status"] == "done"
    assert store.get_item(conn, 3)["status"] == "done"


def test_integrity_scan_marks_an_actionable_recovery_inbox():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/missing", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/present", status="done")
    store.insert_item(conn, 3, "https://tiktok.com/failed", status="failed")
    store.insert_item(conn, 4, "https://tiktok.com/new", status="pending")

    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "2.mp4"), "w").close()
        verify.verify_archive(conn, dl)

    rows = store.page_items(conn, recovery=True)
    assert [row["id"] for row in rows] == [4, 3, 1]


def test_requeue_selected_only_repairs_failed_or_missing_remote_items():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/failed", status="failed")
    store.insert_item(conn, 2, "https://tiktok.com/missing", status="done")
    store.insert_item(conn, 3, "https://tiktok.com/present", status="done")
    store.insert_item(conn, 4, "local://file/4", status="failed")
    store.insert_item(conn, 5, "https://tiktok.com/pending", status="pending")
    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "3.mp4"), "w").close()
        result = verify.requeue_selected(conn, dl, [1, 2, 3, 4, 5, 999])
    assert result == {"requeued": [1, 2], "skipped": 4}
    assert store.get_item(conn, 1)["status"] == "pending"
    assert store.get_item(conn, 2)["status"] == "pending"
    assert store.get_item(conn, 3)["status"] == "done"
    assert store.get_item(conn, 4)["status"] == "failed"
    assert store.get_item(conn, 5)["status"] == "pending"


def test_missing_download_dir_reports_everything_missing():
    conn = _db()
    store.insert_item(conn, 1, "a", status="done")
    report = verify.verify_archive(conn, "/nonexistent/path")
    assert report["missing"]["count"] == 1 and report["ok"] is False


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
