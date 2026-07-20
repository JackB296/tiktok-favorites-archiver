"""Exact duplicate scanning is cached, accurate, and non-destructive."""
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import duplicates, store


def _archive(root):
    conn = store.init_db(store.connect(":memory:"))
    for item_id in (1, 2, 3):
        store.insert_item(
            conn, item_id, f"https://tiktok.com/{item_id}",
            kind="video", status="done",
        )
    for item_id, data in ((1, b"same movie"), (2, b"same movie"), (3, b"other")):
        with open(os.path.join(root, f"{item_id}.mp4"), "wb") as output:
            output.write(data)
    return conn


def test_scan_groups_exact_bytes_and_reuses_unchanged_digests():
    with tempfile.TemporaryDirectory() as root:
        conn = _archive(root)
        first = duplicates.scan(conn, root)
        assert first["scan"] == {"hashed": 3, "reused": 0}
        assert first["group_count"] == 1
        assert first["groups"][0]["item_ids"] == [1, 2]
        assert first["reclaimable_bytes"] == len(b"same movie")
        assert os.path.exists(os.path.join(root, "1.mp4"))
        assert os.path.exists(os.path.join(root, "2.mp4"))

        second = duplicates.scan(conn, root)
        assert second["scan"] == {"hashed": 0, "reused": 3}


def test_changed_and_missing_media_refresh_or_clear_cache():
    with tempfile.TemporaryDirectory() as root:
        conn = _archive(root)
        duplicates.scan(conn, root)
        with open(os.path.join(root, "2.mp4"), "wb") as output:
            output.write(b"now unique and longer")
        os.unlink(os.path.join(root, "3.mp4"))

        report = duplicates.scan(conn, root)
        assert report["group_count"] == 0
        assert report["scan"]["hashed"] == 1
        assert conn.execute(
            "SELECT 1 FROM media_digest WHERE item_id = 3"
        ).fetchone() is None


def test_scan_does_not_block_archive_writes_while_hashing_media():
    with tempfile.TemporaryDirectory() as root:
        db_path = os.path.join(root, "archive.sqlite")
        conn = store.init_db(store.connect(db_path))
        for item_id in (1, 2):
            store.insert_item(
                conn, item_id, f"https://tiktok.com/{item_id}",
                kind="video", status="done",
            )
            with open(os.path.join(root, f"{item_id}.mp4"), "wb") as output:
                output.write(b"media")

        hashing_second_file = threading.Event()
        resume_scan = threading.Event()
        original_open_media = duplicates._open_media

        def pause_before_second_file(download_dir, item_id):
            if item_id == 2:
                hashing_second_file.set()
                assert resume_scan.wait(2)
            return original_open_media(download_dir, item_id)

        duplicates._open_media = pause_before_second_file
        failures = []

        def scan():
            try:
                duplicates.scan(conn, root)
            except Exception as error:
                failures.append(error)

        worker = threading.Thread(target=scan)
        worker.start()
        try:
            assert hashing_second_file.wait(2)
            writer = store.connect(db_path)
            try:
                writer.execute("PRAGMA busy_timeout=100")
                store.set_metadata(writer, 1, "still writable", "author")
                assert store.get_item(writer, 1)["caption"] == "still writable"
            finally:
                writer.close()
        finally:
            resume_scan.set()
            worker.join(2)
            duplicates._open_media = original_open_media
            conn.close()
        assert not failures


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
