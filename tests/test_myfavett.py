"""myfaveTT folder planning and safe local-media adoption."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import media_index, myfavett, store


def _write_mp4(path, payload=b"myfavett"):
    with open(path, "wb") as target:
        target.write(b"\x00\x00\x00\x18ftypisom" + payload)


def _inspect(_path):
    return media_index.MediaFacts(4.5, 720, 1280, "h264", 42, True)


def _thumbnail(_source, target, _width):
    with open(target, "wb") as output:
        output.write(b"thumb")


def test_plan_recognizes_current_layout_matches_slots_and_skips_existing_media():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://www.tiktok.com/@gone/video/11111", status="expired")
    store.insert_item(conn, 2, "https://www.tiktok.com/@saved/video/22222", status="done")
    store.insert_item(conn, 3, "https://www.tiktok.com/@photos/photo/44444", status="expired")
    with tempfile.TemporaryDirectory() as downloads:
        _write_mp4(os.path.join(downloads, "2.mp4"))
        plan = myfavett.plan_import(conn, downloads, [
            "archive/data/Favorites/videos/11111.mp4",
            "archive/data/Likes/videos/11111.mp4",
            "archive/data/Following/42/videos/22222.mp4",
            "archive/data/Likes/covers/11111.jpg",
            "archive/data/Likes/videos/33333.mp4",
            "archive/data/Favorites/videos/44444.mp4",
        ])

    assert plan["counts"] == {
        "ready": 3, "already_archived": 1, "matched_slots": 3, "new_local_items": 1,
    }
    assert plan["duplicate_files"] == 1 and plan["ignored_paths"] == 1
    by_id = {item["video_id"]: item for item in plan["items"]}
    assert by_id["11111"]["item_id"] == 1 and by_id["11111"]["match"] == "archive_slot"
    assert by_id["44444"]["item_id"] == 3 and by_id["44444"]["match"] == "archive_slot"
    assert by_id["33333"]["item_id"] is None and by_id["33333"]["match"] == "new_local_item"


def test_adopt_fills_unavailable_slot_preserves_identity_and_is_idempotent():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 7, "https://www.tiktok.com/@gone/video/77777", status="expired")
    store.set_metadata(conn, 7, "preserve me", "gone")
    with tempfile.TemporaryDirectory() as downloads:
        staged = os.path.join(downloads, ".upload")
        _write_mp4(staged)
        result = myfavett.adopt_video(
            conn, downloads, "77777", staged,
            source_path="backup/data/Favorites/videos/77777.mp4",
            inspect=_inspect, make_thumbnail=_thumbnail,
        )
        again = myfavett.adopt_video(
            conn, downloads, "77777", "unused",
            source_path="backup/data/Favorites/videos/77777.mp4",
            inspect=_inspect, make_thumbnail=_thumbnail,
        )
        assert os.path.isfile(os.path.join(downloads, "7.mp4"))
        assert os.path.isfile(os.path.join(downloads, "manifest.csv"))

    row = store.get_item(conn, 7)
    assert result == {"status": "imported", "item_id": 7, "created": False, "matched_slot": True}
    assert again == {"status": "already_archived", "item_id": 7, "created": False}
    assert row["status"] == "done" and row["caption"] == "preserve me" and row["link"].endswith("/77777")


def test_adopt_unmatched_video_creates_local_only_item_and_rolls_back_invalid_media():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as downloads:
        staged = os.path.join(downloads, ".upload")
        _write_mp4(staged)
        result = myfavett.adopt_video(
            conn, downloads, "88888", staged,
            source_path="archive/videos/88888.mp4",
            inspect=_inspect, make_thumbnail=_thumbnail,
        )
        assert store.get_item(conn, result["item_id"])["link"] == "local://myfavett/88888"
        again = myfavett.adopt_video(
            conn, downloads, "88888", "unused",
            source_path="archive/videos/88888.mp4",
            inspect=_inspect, make_thumbnail=_thumbnail,
        )
        assert again == {"status": "already_archived", "item_id": result["item_id"], "created": False}

        invalid = os.path.join(downloads, ".invalid")
        with open(invalid, "wb") as target:
            target.write(b"not mp4")
        try:
            myfavett.adopt_video(
                conn, downloads, "99999", invalid,
                source_path="archive/videos/99999.mp4",
                inspect=_inspect, make_thumbnail=_thumbnail,
            )
        except Exception:
            pass
        else:
            raise AssertionError("invalid media should fail")
        assert conn.execute("SELECT 1 FROM item WHERE link = 'local://myfavett/99999'").fetchone() is None


if __name__ == "__main__":
    import traceback
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
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
