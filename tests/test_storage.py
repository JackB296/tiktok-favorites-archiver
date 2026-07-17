"""Mounted Storage locations and verified Media placements."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import storage, store


def _archive(root):
    downloads = os.path.join(root, "downloads")
    data = os.path.join(root, "data")
    os.makedirs(downloads)
    os.makedirs(data)
    db_path = os.path.join(data, "archive.db")
    conn = store.init_db(store.connect(db_path))
    return conn, downloads, db_path


def test_locations_persist_unique_names_and_canonical_mounted_paths():
    with tempfile.TemporaryDirectory() as root:
        conn, downloads, db_path = _archive(root)
        mounted = os.path.join(root, "mounted", "..", "mounted")
        os.makedirs(os.path.realpath(mounted))

        location = storage.create_location(
            conn, "NAS archive", mounted, downloads, db_path,
        )

        assert location["name"] == "NAS archive"
        assert location["path"] == os.path.realpath(mounted)
        assert location["available"] is True
        assert storage.list_locations(conn)[0]["id"] == location["id"]

        try:
            storage.create_location(conn, "NAS archive", os.path.realpath(mounted), downloads, db_path)
        except storage.StorageError as exc:
            assert "name" in str(exc).lower() or "path" in str(exc).lower()
        else:
            raise AssertionError("duplicate location was accepted")


def test_location_validation_rejects_overlap_missing_files_and_unwritable_paths():
    with tempfile.TemporaryDirectory() as root:
        conn, downloads, db_path = _archive(root)
        cases = [
            downloads,
            os.path.dirname(downloads),
            os.path.dirname(db_path),
            os.path.join(root, "missing"),
            db_path,
        ]
        for path in cases:
            try:
                storage.create_location(conn, "Bad", path, downloads, db_path)
            except storage.StorageError:
                pass
            else:
                raise AssertionError(f"accepted unsafe location {path}")


def test_location_health_records_loss_and_recovery():
    with tempfile.TemporaryDirectory() as root:
        conn, downloads, db_path = _archive(root)
        mounted = os.path.join(root, "mounted")
        os.makedirs(mounted)
        location = storage.create_location(conn, "USB", mounted, downloads, db_path)

        os.rmdir(mounted)
        unhealthy = storage.check_location(conn, location["id"], downloads, db_path)
        assert unhealthy["available"] is False
        assert unhealthy["last_error"]

        os.makedirs(mounted)
        healthy = storage.check_location(conn, location["id"], downloads, db_path)
        assert healthy["available"] is True
        assert healthy["last_error"] is None


def test_referenced_locations_cannot_be_deleted():
    with tempfile.TemporaryDirectory() as root:
        conn, downloads, db_path = _archive(root)
        mounted = os.path.join(root, "mounted")
        os.makedirs(mounted)
        location = storage.create_location(conn, "NAS", mounted, downloads, db_path)
        store.insert_item(conn, 1, "https://tiktok.com/1")
        store.record_media_placement(
            conn, 1, location["id"], "items/1", 10, "a" * 64, verified=True,
        )

        try:
            storage.delete_location(conn, location["id"])
        except storage.StorageConflictError as exc:
            assert "referenced" in str(exc)
        else:
            raise AssertionError("referenced location was deleted")


def test_item_media_manifest_is_complete_contained_and_deterministic():
    with tempfile.TemporaryDirectory() as root:
        conn, downloads, _db_path = _archive(root)
        store.insert_item(conn, 7, "https://tiktok.com/7", status="done")
        assets = os.path.join(downloads, "7")
        os.makedirs(assets)
        os.makedirs(os.path.join(downloads, ".archive", "thumbnails"))
        os.makedirs(os.path.join(downloads, ".archive", "custom-thumbnails"))
        os.makedirs(os.path.join(downloads, ".archive", "replaced"))
        files = {
            "7.mp4": b"movie",
            "7.nfo": b"metadata",
            "7.jpg": b"poster",
            "7/02.jpg": b"two",
            "7/01.jpg": b"one",
            "7/audio.mp3": b"sound",
            "7/skip.tmp": b"temporary",
            ".archive/thumbnails/7.webp": b"thumb",
            ".archive/custom-thumbnails/7.png": b"custom",
            ".archive/replaced/7.mp4": b"backup",
        }
        for relative, content in files.items():
            path = os.path.join(downloads, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as target:
                target.write(content)
        store.record_manual_media(
            conn, 7,
            custom_thumbnail_path=".archive/custom-thumbnails/7.png",
        )
        conn.execute(
            "UPDATE item SET thumbnail_path = ? WHERE id = 7",
            (".archive/thumbnails/7.webp",),
        )
        conn.commit()

        first = storage.item_media_manifest(downloads, store.get_item(conn, 7))
        second = storage.item_media_manifest(downloads, store.get_item(conn, 7))

        assert first == second
        assert [entry["path"] for entry in first["files"]] == sorted(
            relative for relative in files if relative != "7/skip.tmp"
        )
        assert first["file_count"] == 9
        assert first["byte_count"] == sum(
            len(content) for relative, content in files.items() if relative != "7/skip.tmp"
        )
        assert len(first["digest"]) == 64


def test_item_media_manifest_rejects_a_database_path_escape():
    with tempfile.TemporaryDirectory() as root:
        conn, downloads, _db_path = _archive(root)
        store.insert_item(conn, 1, "https://tiktok.com/1")
        conn.execute("UPDATE item SET custom_thumbnail_path = '../secret.jpg' WHERE id = 1")
        conn.commit()
        try:
            storage.item_media_manifest(downloads, store.get_item(conn, 1))
        except storage.StorageError as exc:
            assert "escapes" in str(exc)
        else:
            raise AssertionError("path traversal was accepted")


def test_copy_preview_resume_move_and_restore_are_checksum_guarded():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as mounted:
        conn, downloads, db_path = _archive(root)
        location = storage.create_location(conn, "NAS", mounted, downloads, db_path)
        store.insert_item(conn, 1, "https://tiktok.com/1", status="done")
        with open(os.path.join(downloads, "1.mp4"), "wb") as target:
            target.write(b"original movie")

        preview = storage.preview_transfer(conn, downloads, location["id"], [1])
        assert preview == {
            "items": 1, "files": 1, "bytes": 14,
            "conflicts": 0, "already_verified": 0,
        }
        copied = storage.copy_items(conn, downloads, location["id"], [1])
        assert copied["items"] == 1 and copied["files"] == 1
        assert store.get_item(conn, 1)["offloaded"] == 0
        assert store.media_placements(conn, 1)[0]["verified"] == 1

        resumed = storage.copy_items(conn, downloads, location["id"], [1])
        assert resumed["files"] == 0 and resumed["skipped_files"] == 1
        assert storage.preview_transfer(conn, downloads, location["id"], [1])["already_verified"] == 1

        moved = storage.move_items(conn, downloads, location["id"], [1])
        assert moved["moved"] == 1
        assert not os.path.exists(os.path.join(downloads, "1.mp4"))
        assert store.get_item(conn, 1)["offloaded"] == 1

        restored = storage.restore_items(conn, downloads, location["id"], [1])
        assert restored == {"restored": 1}
        assert open(os.path.join(downloads, "1.mp4"), "rb").read() == b"original movie"
        assert store.get_item(conn, 1)["offloaded"] == 0
        assert os.path.exists(os.path.join(mounted, "items", "1", "1.mp4"))


def test_failed_copy_publishes_no_verified_placement_and_never_deletes_local():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as mounted:
        conn, downloads, db_path = _archive(root)
        location = storage.create_location(conn, "NAS", mounted, downloads, db_path)
        store.insert_item(conn, 1, "https://tiktok.com/1", status="done")
        local = os.path.join(downloads, "1.mp4")
        with open(local, "wb") as target:
            target.write(b"good")

        def corrupt_copier(_source, target):
            with open(target, "wb") as output:
                output.write(b"bad")

        try:
            storage.move_items(
                conn, downloads, location["id"], [1], copier=corrupt_copier,
            )
        except storage.StorageError as exc:
            assert "checksum" in str(exc)
        else:
            raise AssertionError("corrupt copy was accepted")
        assert store.media_placements(conn, 1) == []
        assert os.path.exists(local)
        assert store.get_item(conn, 1)["offloaded"] == 0


def test_legacy_offloaded_rows_cannot_claim_a_verified_restore():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as mounted:
        conn, downloads, db_path = _archive(root)
        location = storage.create_location(conn, "NAS", mounted, downloads, db_path)
        store.insert_item(conn, 1, "https://tiktok.com/1", status="done")
        store.set_offloaded(conn, [1], True)
        try:
            storage.restore_items(conn, downloads, location["id"], [1])
        except storage.StorageError as exc:
            assert "no verified" in str(exc)
        else:
            raise AssertionError("legacy Offloaded row claimed verification")
        assert store.get_item(conn, 1)["offloaded"] == 1


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
