"""Opt-in, atomic metadata embedding for portable archive MP4s."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import layout, portable_metadata, store


def _library():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://www.tiktok.com/@cook/video/123")
    conn.execute(
        "UPDATE item SET status = 'done', caption = 'Dinner', author = 'Cook', "
        "description = 'Full recipe', source_posted_at = '2026-07-01T12:00:00+00:00' "
        "WHERE id = 1"
    )
    conn.commit()
    return conn


def test_embed_library_atomically_adds_tags_artwork_and_subtitles_once():
    conn = _library()
    commands = []
    with tempfile.TemporaryDirectory() as downloads:
        movie = layout.movie(downloads, 1)
        with open(movie, "wb") as output:
            output.write(b"original-media")
        with open(layout.poster(downloads, 1), "wb") as output:
            output.write(b"poster")
        with open(os.path.join(downloads, "1.en.vtt"), "w", encoding="utf-8") as output:
            output.write("WEBVTT\n")
        with open(os.path.join(downloads, "1.info.json"), "w", encoding="utf-8") as output:
            json.dump({"subtitle_files": {"en": "1.en.vtt"}}, output)

        def run(command, **_kwargs):
            commands.append(command)
            with open(command[-1], "wb") as output:
                output.write(b"portable-media")

        validate = lambda path: open(path, "rb").read() == b"portable-media"
        first = portable_metadata.embed_library(
            conn, downloads, runner=run, validate=validate,
        )
        second = portable_metadata.embed_library(
            conn, downloads, runner=run, validate=validate,
        )

        assert open(movie, "rb").read() == b"portable-media"
        assert store.get_item(conn, 1)["media_size"] == len(b"portable-media")

    assert first == {"embedded": 1, "skipped": 0, "failed": 0}
    assert second == {"embedded": 0, "skipped": 1, "failed": 0}
    assert len(commands) == 1
    command = commands[0]
    assert command[0] == "ffmpeg"
    assert command[command.index("-c:v:0") + 1] == "copy"
    assert command[command.index("-c:a") + 1] == "copy"
    assert "attached_pic" in command and "mov_text" in command
    assert "title=Dinner" in command and "artist=Cook" in command


def test_failed_embedding_preserves_the_original_media_and_records_retryable_error():
    conn = _library()
    with tempfile.TemporaryDirectory() as downloads:
        movie = layout.movie(downloads, 1)
        with open(movie, "wb") as output:
            output.write(b"original-media")

        def run(command, **_kwargs):
            with open(command[-1], "wb") as output:
                output.write(b"broken")

        result = portable_metadata.embed_library(
            conn, downloads, runner=run, validate=lambda _path: False,
        )

        assert open(movie, "rb").read() == b"original-media"
        assert not [name for name in os.listdir(downloads) if "portable" in name]

    assert result == {"embedded": 0, "skipped": 0, "failed": 1}
    item = store.get_item(conn, 1)
    assert item["portable_metadata_status"] == "error"
    assert "validation" in item["portable_metadata_error"]


def test_real_ffmpeg_embedding_keeps_playable_av_and_adds_tags_artwork_and_subtitles():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return
    conn = _library()
    with tempfile.TemporaryDirectory() as downloads:
        movie = layout.movie(downloads, 1)
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=blue:s=72x128:d=0.8", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=0.8", "-shortest", "-c:v", "libx264",
            "-c:a", "aac", "-pix_fmt", "yuv420p", movie,
        ], check=True)
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=red:s=72x128", "-frames:v", "1", layout.poster(downloads, 1),
        ], check=True)
        with open(os.path.join(downloads, "1.en.vtt"), "w", encoding="utf-8") as output:
            output.write("WEBVTT\n\n00:00:00.000 --> 00:00:00.500\nDinner time\n")
        with open(os.path.join(downloads, "1.info.json"), "w", encoding="utf-8") as output:
            json.dump({"subtitle_files": {"en": "1.en.vtt"}}, output)

        assert portable_metadata.embed_library(conn, downloads) == {
            "embedded": 1, "skipped": 0, "failed": 0,
        }
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", movie,
        ], check=True, capture_output=True, text=True)
        saved = json.loads(probe.stdout)
        tags = saved["format"]["tags"]
        assert tags["title"] == "Dinner" and tags["artist"] == "Cook"
        assert "https://www.tiktok.com/@cook/video/123" in tags["comment"]
        assert any(stream["codec_type"] == "audio" for stream in saved["streams"])
        assert any(stream["codec_type"] == "subtitle" and stream["codec_name"] == "mov_text" for stream in saved["streams"])
        assert any(stream.get("disposition", {}).get("attached_pic") == 1 for stream in saved["streams"])


def test_embed_library_stream_copies_multiple_movies_concurrently_and_records_every_result():
    conn = store.init_db(store.connect(":memory:"))
    for item_id in range(1, 21):
        store.insert_item(conn, item_id, f"https://tiktok.com/video/{item_id}", status="done")
    lock = threading.Lock()
    active = 0
    peak = 0

    def run(command, **_kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.05)
            with open(command[-1], "wb") as output:
                output.write(b"portable")
        finally:
            with lock:
                active -= 1

    with tempfile.TemporaryDirectory() as downloads:
        for item_id in range(1, 21):
            with open(layout.movie(downloads, item_id), "wb") as output:
                output.write(b"original")
        started = time.perf_counter()
        result = portable_metadata.embed_library(
            conn, downloads, runner=run, validate=lambda _path: True, workers=4,
        )
        elapsed = time.perf_counter() - started

    assert result == {"embedded": 20, "skipped": 0, "failed": 0}
    assert peak == 4
    assert elapsed < 0.40
    assert conn.execute(
        "SELECT COUNT(*) FROM item WHERE portable_metadata_status = 'ok'"
    ).fetchone()[0] == 20


if __name__ == "__main__":
    test_embed_library_atomically_adds_tags_artwork_and_subtitles_once()
    print("PASS test_embed_library_atomically_adds_tags_artwork_and_subtitles_once")
    test_failed_embedding_preserves_the_original_media_and_records_retryable_error()
    print("PASS test_failed_embedding_preserves_the_original_media_and_records_retryable_error")
    test_real_ffmpeg_embedding_keeps_playable_av_and_adds_tags_artwork_and_subtitles()
    print("PASS test_real_ffmpeg_embedding_keeps_playable_av_and_adds_tags_artwork_and_subtitles")
    test_embed_library_stream_copies_multiple_movies_concurrently_and_records_every_result()
    print("PASS test_embed_library_stream_copies_multiple_movies_concurrently_and_records_every_result")
