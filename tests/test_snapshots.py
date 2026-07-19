"""Portable snapshot creation, validation, and resume behavior."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import layout, snapshots, stories, store


def _archive(root):
    downloads = os.path.join(root, "downloads")
    os.makedirs(downloads)
    db_path = os.path.join(root, "archive.db")
    conn = store.init_db(store.connect(db_path))
    store.insert_item(conn, 1, "https://tiktok.com/1", status="done")
    with open(os.path.join(downloads, "1.mp4"), "wb") as target:
        target.write(b"movie")
    return conn, db_path, downloads


def test_metadata_and_complete_snapshot_layouts_round_trip():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as destination:
        conn, db_path, downloads = _archive(root)
        metadata = snapshots.create_snapshot(
            conn, db_path, downloads, destination, "metadata", "metadata",
        )
        complete = snapshots.create_snapshot(
            conn, db_path, downloads, destination, "complete", "complete",
        )

        assert os.path.isfile(os.path.join(metadata["path"], "snapshot.json"))
        assert os.path.isfile(os.path.join(metadata["path"], "database", "archive.db"))
        assert not os.path.exists(os.path.join(metadata["path"], "media"))
        assert open(os.path.join(complete["path"], "media", "1.mp4"), "rb").read() == b"movie"
        assert snapshots.validate_snapshot(metadata["path"])["mode"] == "metadata"
        assert snapshots.validate_snapshot(complete["path"])["mode"] == "complete"
        assert [entry["state"] for entry in snapshots.list_snapshots(destination)] == [
            "complete", "complete",
        ]


def test_complete_snapshot_round_trips_rendered_story_media():
    with tempfile.TemporaryDirectory() as source_root, \
            tempfile.TemporaryDirectory() as snapshot_dir, \
            tempfile.TemporaryDirectory() as target_root:
        source, source_db, source_downloads = _archive(source_root)
        source.execute("UPDATE item SET duration_s = 5 WHERE id = 1")
        source.commit()
        story = stories.create_story(source, {
            "name": "Saved reel",
            "chapters": [{
                "item_id": 1,
                "title": "Chapter",
                "start_s": 0,
                "end_s": 5,
            }],
        })
        os.makedirs(layout.stories_dir(source_downloads))
        with open(layout.story_movie(source_downloads, story["id"]), "wb") as target:
            target.write(b"rendered story")
        stories.record_render_success(
            source, story["id"], layout.story_relpath(story["id"]),
        )

        snapshot = snapshots.create_snapshot(
            source, source_db, source_downloads, snapshot_dir,
            "with-story", "complete",
        )["path"]
        archived_story = os.path.join(
            snapshot, "media", *layout.story_relpath(story["id"]).split("/"),
        )
        assert open(archived_story, "rb").read() == b"rendered story"

        target_downloads = os.path.join(target_root, "downloads")
        os.makedirs(target_downloads)
        target_db = os.path.join(target_root, "archive.db")
        target = store.init_db(store.connect(target_db))
        plan = snapshots.restore_plan(snapshot, target, target_downloads)
        snapshots.apply_restore(
            snapshot, target, target_db, target_downloads,
            snapshot_dir, plan["token"],
        )

        assert open(
            layout.story_movie(target_downloads, story["id"]), "rb",
        ).read() == b"rendered story"
        assert stories.get_story(target, story["id"])["rendered_path"] == \
            layout.story_relpath(story["id"])


def test_snapshot_manifest_is_sorted_relative_and_contains_no_source_paths():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as destination:
        conn, db_path, downloads = _archive(root)
        result = snapshots.create_snapshot(
            conn, db_path, downloads, destination, "portable", "complete",
        )
        raw = open(os.path.join(result["path"], "snapshot.json"), encoding="utf-8").read()
        metadata = json.loads(raw)
        paths = [entry["path"] for entry in metadata["files"]]
        assert paths == sorted(paths)
        assert all(not os.path.isabs(path) and ".." not in path.split("/") for path in paths)
        assert root not in raw and destination not in raw


def test_snapshot_removes_spotify_tokens_and_token_bytes():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as destination:
        conn, db_path, downloads = _archive(root)
        access_token = "snapshot-access-token-should-never-leave-this-database"
        refresh_token = "snapshot-refresh-token-should-never-leave-this-database"
        store.save_spotify_auth(
            conn,
            client_id="public-client-id",
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=9999999999,
            account_name="Archive owner",
        )
        result = snapshots.create_snapshot(
            conn, db_path, downloads, destination, "sanitized", "metadata",
        )
        database = os.path.join(result["path"], "database", "archive.db")
        copied = store.connect(database)
        try:
            auth = store.get_spotify_auth(copied)
            assert auth["client_id"] == "public-client-id"
            assert auth["access_token"] is None
            assert auth["refresh_token"] is None
            assert auth["expires_at"] is None
        finally:
            copied.close()
        raw = open(database, "rb").read()
        assert access_token.encode() not in raw
        assert refresh_token.encode() not in raw


def test_corruption_and_traversal_are_rejected():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as destination:
        conn, db_path, downloads = _archive(root)
        result = snapshots.create_snapshot(
            conn, db_path, downloads, destination, "bad", "metadata",
        )
        database = os.path.join(result["path"], "database", "archive.db")
        with open(database, "ab") as target:
            target.write(b"corrupt")
        try:
            snapshots.validate_snapshot(result["path"])
        except snapshots.SnapshotError as exc:
            assert "corrupt" in str(exc)
        else:
            raise AssertionError("corrupt snapshot passed")

        metadata_path = os.path.join(result["path"], "snapshot.json")
        metadata = json.load(open(metadata_path, encoding="utf-8"))
        metadata["files"][0]["path"] = "../escape"
        with open(metadata_path, "w", encoding="utf-8") as target:
            json.dump(metadata, target)
        try:
            snapshots.validate_snapshot(result["path"])
        except snapshots.SnapshotError as exc:
            assert "unsafe" in str(exc)
        else:
            raise AssertionError("traversal passed")


def test_unmanifested_files_and_incompatible_database_schema_are_rejected():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as destination:
        conn, db_path, downloads = _archive(root)
        result = snapshots.create_snapshot(
            conn, db_path, downloads, destination, "strict", "metadata",
        )
        extra = os.path.join(result["path"], "unmanifested.txt")
        with open(extra, "w", encoding="utf-8") as target:
            target.write("not checksummed")
        try:
            snapshots.validate_snapshot(result["path"])
        except snapshots.SnapshotError as exc:
            assert "manifest" in str(exc)
        else:
            raise AssertionError("unmanifested snapshot file passed")
        os.unlink(extra)

        metadata_path = os.path.join(result["path"], "snapshot.json")
        metadata = json.load(open(metadata_path, encoding="utf-8"))
        metadata["schema_version"] = snapshots.migrations.CURRENT_SCHEMA_VERSION + 1
        with open(metadata_path, "w", encoding="utf-8") as target:
            json.dump(metadata, target)
        try:
            snapshots.validate_snapshot(result["path"])
        except snapshots.SnapshotError as exc:
            assert "schema" in str(exc)
        else:
            raise AssertionError("future snapshot schema passed")


class _Stop:
    def should_continue(self):
        return False

    def progress(self, _event):
        pass


def test_stopped_complete_snapshot_remains_partial_and_can_resume():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as destination:
        conn, db_path, downloads = _archive(root)
        stopped = snapshots.create_snapshot(
            conn, db_path, downloads, destination, "resume", "complete", control=_Stop(),
        )
        assert stopped["partial"] is True
        assert stopped["path"].endswith(".partial")
        assert snapshots.list_snapshots(destination)[0]["state"] == "partial"

        resumed = snapshots.create_snapshot(
            conn, db_path, downloads, destination, "resume", "complete",
        )
        assert resumed["partial"] is False
        assert not os.path.exists(stopped["path"])
        assert snapshots.validate_snapshot(resumed["path"])["mode"] == "complete"


def test_restore_plan_and_empty_complete_restore_reproduce_archive():
    with tempfile.TemporaryDirectory() as source_root, tempfile.TemporaryDirectory() as snapshot_dir, tempfile.TemporaryDirectory() as target_root:
        source, source_db, source_downloads = _archive(source_root)
        snapshot = snapshots.create_snapshot(
            source, source_db, source_downloads, snapshot_dir, "source", "complete",
        )["path"]
        target_downloads = os.path.join(target_root, "downloads")
        os.makedirs(target_downloads)
        target_db = os.path.join(target_root, "archive.db")
        target = store.init_db(store.connect(target_db))
        plan = snapshots.restore_plan(snapshot, target, target_downloads)
        assert plan["requires_replace"] is False
        assert plan["snapshot_items"] == 1 and plan["required_bytes"] == 5

        result = snapshots.apply_restore(
            snapshot, target, target_db, target_downloads, snapshot_dir, plan["token"],
        )
        assert result["restored"] is True and result["rollback_snapshot"] is None
        assert store.get_item(target, 1)["link"] == "https://tiktok.com/1"
        assert open(os.path.join(target_downloads, "1.mp4"), "rb").read() == b"movie"


def test_replacement_requires_confirmation_and_creates_valid_rollback():
    with tempfile.TemporaryDirectory() as source_root, tempfile.TemporaryDirectory() as snapshot_dir, tempfile.TemporaryDirectory() as target_root:
        source, source_db, source_downloads = _archive(source_root)
        snapshot = snapshots.create_snapshot(
            source, source_db, source_downloads, snapshot_dir, "source", "metadata",
        )["path"]
        target_downloads = os.path.join(target_root, "downloads")
        os.makedirs(target_downloads)
        target_db = os.path.join(target_root, "archive.db")
        target = store.init_db(store.connect(target_db))
        store.insert_item(target, 9, "https://tiktok.com/old", status="done")
        with open(os.path.join(target_downloads, "9.mp4"), "wb") as movie:
            movie.write(b"old")
        plan = snapshots.restore_plan(snapshot, target, target_downloads)
        try:
            snapshots.apply_restore(
                snapshot, target, target_db, target_downloads, snapshot_dir, plan["token"],
            )
        except snapshots.SnapshotError as exc:
            assert "confirmation" in str(exc)
        else:
            raise AssertionError("replacement ran without confirmation")

        result = snapshots.apply_restore(
            snapshot, target, target_db, target_downloads, snapshot_dir,
            plan["token"], confirmation="REPLACE ARCHIVE",
        )
        assert store.get_item(target, 1) is not None
        assert store.get_item(target, 9) is None
        assert snapshots.validate_snapshot(result["rollback_snapshot"])["mode"] == "complete"


def test_restore_staging_failure_leaves_current_database_usable():
    with tempfile.TemporaryDirectory() as source_root, tempfile.TemporaryDirectory() as snapshot_dir, tempfile.TemporaryDirectory() as target_root:
        source, source_db, source_downloads = _archive(source_root)
        snapshot = snapshots.create_snapshot(
            source, source_db, source_downloads, snapshot_dir, "source", "complete",
        )["path"]
        target_downloads = os.path.join(target_root, "downloads")
        os.makedirs(target_downloads)
        target_db = os.path.join(target_root, "archive.db")
        target = store.init_db(store.connect(target_db))
        store.insert_item(target, 9, "https://tiktok.com/old")
        plan = snapshots.restore_plan(snapshot, target, target_downloads)

        def corrupt(_source, destination):
            with open(destination, "wb") as output:
                output.write(b"bad")

        try:
            snapshots.apply_restore(
                snapshot, target, target_db, target_downloads, snapshot_dir,
                plan["token"], confirmation="REPLACE ARCHIVE", copier=corrupt,
            )
        except snapshots.SnapshotError:
            pass
        else:
            raise AssertionError("corrupt staging succeeded")
        assert store.get_item(target, 9)["link"] == "https://tiktok.com/old"


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
