"""Tests for safe, fixed-path manual Archive media replacement."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import manual_media, media_index, store
from server.archive_items import ArchiveItems


def _mp4_bytes(payload=b"replacement"):
    return b"\x00\x00\x00\x18ftypisom" + payload


def _write(path, data):
    with open(path, "wb") as file:
        file.write(data)


def test_replacement_video_uses_item_path_refreshes_facts_and_preserves_metadata():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 7, "https://tiktok.com/original", kind="video", status="failed")
    store.set_metadata(conn, 7, "keep this caption", "keep this creator")

    with tempfile.TemporaryDirectory() as download_dir:
        target = os.path.join(download_dir, "7.mp4")
        staged = os.path.join(download_dir, ".replacement.upload")
        _write(target, b"old video")
        _write(staged, _mp4_bytes())

        result = manual_media.replace_item_media(
            conn,
            download_dir,
            7,
            staged_video=staged,
            inspect=lambda _path: media_index.MediaFacts(12.5, 720, 1280, "h264", 99, False),
            make_thumbnail=lambda _source, thumbnail, _width: _write(thumbnail, b"generated thumb"),
        )

        assert open(target, "rb").read() == _mp4_bytes()
        assert os.path.isfile(os.path.join(download_dir, ".archive", "thumbnails", "7.webp"))

    row = store.get_item(conn, 7)
    assert result == {"video_replaced": True, "thumbnail_replaced": False}
    assert row["status"] == "done" and row["error"] is None
    assert row["caption"] == "keep this caption" and row["author"] == "keep this creator"
    assert row["has_audio"] == 0 and row["duration_s"] == 12.5


def test_invalid_video_never_replaces_existing_media():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 3, "https://tiktok.com/original", kind="video", status="done")

    with tempfile.TemporaryDirectory() as download_dir:
        target = os.path.join(download_dir, "3.mp4")
        staged = os.path.join(download_dir, ".invalid.upload")
        _write(target, b"healthy video")
        _write(staged, b"not an mp4")

        try:
            manual_media.replace_item_media(conn, download_dir, 3, staged_video=staged)
        except manual_media.MediaReplacementError as error:
            assert "MP4" in str(error)
        else:
            raise AssertionError("invalid video should be rejected")

        assert open(target, "rb").read() == b"healthy video"


def test_custom_thumbnail_is_projected_and_survives_generated_index_updates():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 5, "https://tiktok.com/original", kind="video", status="done")

    with tempfile.TemporaryDirectory() as download_dir:
        staged = os.path.join(download_dir, ".thumbnail.upload")
        _write(staged, b"\x89PNG\r\n\x1a\nthumbnail")

        result = manual_media.replace_item_media(conn, download_dir, 5, staged_thumbnail=staged)
        store.record_media_index(
            conn,
            5,
            {"duration_s": 1, "width": 10, "height": 20, "codec": "h264", "file_size": 30, "has_audio": True, "thumbnail_path": ".archive/thumbnails/5.webp"},
            "30:1",
        )
        item = ArchiveItems(conn, download_dir).get(5)

        assert result == {"video_replaced": False, "thumbnail_replaced": True}
        assert item["thumbnail_url"] == "/media/.archive/custom-thumbnails/5.png"
        assert os.path.isfile(os.path.join(download_dir, ".archive", "custom-thumbnails", "5.png"))


def test_replacement_requires_at_least_one_file_and_an_existing_item():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as download_dir:
        for item_id, kwargs, message in (
            (1, {}, "at least one"),
            (99, {"staged_thumbnail": os.path.join(download_dir, "missing")}, "not found"),
        ):
            try:
                manual_media.replace_item_media(conn, download_dir, item_id, **kwargs)
            except manual_media.MediaReplacementError as error:
                assert message in str(error)
            else:
                raise AssertionError("invalid replacement should fail")


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
