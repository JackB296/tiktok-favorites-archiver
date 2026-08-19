"""Safe backlog repair for already-archived videos with no usable sound."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import audio_repair, layout, media_index, store


def _silent_item(conn, item_id=1):
    store.insert_item(
        conn, item_id, f"https://www.tiktok.com/@cook/video/{item_id}",
        status="done", kind="video",
    )
    store.set_metadata(conn, item_id, "keep caption", "keep creator")
    store.record_media_index(conn, item_id, {
        "thumbnail_path": None, "duration_s": 10, "width": 1080,
        "height": 1920, "codec": "h264", "file_size": 10,
        "has_audio": True, "audio_silent": True,
    }, "old")


def test_backlog_audio_repair_atomically_replaces_silent_media_and_keeps_identity():
    conn = store.init_db(store.connect(":memory:"))
    _silent_item(conn)
    with tempfile.TemporaryDirectory() as downloads:
        movie = layout.movie(downloads, 1)
        with open(movie, "wb") as output:
            output.write(b"silent-original")

        def download(_link, destination):
            with open(destination, "wb") as output:
                output.write(b"audible-repair")
            return True

        result = audio_repair.run_audio_repair(
            conn, downloads, download=download,
            inspect=lambda _path: media_index.MediaFacts(
                10, 1080, 1920, "h264", len(b"audible-repair"), True, False,
            ),
        )

        assert open(movie, "rb").read() == b"audible-repair"
        assert open(layout.replaced_movie(downloads, 1), "rb").read() == b"silent-original"

    item = store.get_item(conn, 1)
    assert result == {"completed": 1, "total": 1, "repaired": 1, "failed": 0}
    assert item["id"] == 1 and item["caption"] == "keep caption" and item["author"] == "keep creator"
    assert item["has_audio"] == 1 and item["audio_silent"] == 0
    assert item["download_source"] == "yt-dlp"


def test_backlog_audio_repair_rejects_another_silent_candidate_without_touching_media():
    conn = store.init_db(store.connect(":memory:"))
    _silent_item(conn)
    with tempfile.TemporaryDirectory() as downloads:
        movie = layout.movie(downloads, 1)
        with open(movie, "wb") as output:
            output.write(b"silent-original")

        def download(_link, destination):
            with open(destination, "wb") as output:
                output.write(b"still-silent")
            return True

        result = audio_repair.run_audio_repair(
            conn, downloads, download=download,
            inspect=lambda _path: media_index.MediaFacts(
                10, 720, 1280, "h264", len(b"still-silent"), True, True,
            ),
        )

        assert open(movie, "rb").read() == b"silent-original"
        assert not os.path.exists(layout.replaced_movie(downloads, 1))

    assert result == {"completed": 1, "total": 1, "repaired": 0, "failed": 1}
    assert store.get_item(conn, 1)["audio_silent"] == 1


if __name__ == "__main__":
    test_backlog_audio_repair_atomically_replaces_silent_media_and_keeps_identity()
    print("PASS test_backlog_audio_repair_atomically_replaces_silent_media_and_keeps_identity")
    test_backlog_audio_repair_rejects_another_silent_candidate_without_touching_media()
    print("PASS test_backlog_audio_repair_rejects_another_silent_candidate_without_touching_media")
