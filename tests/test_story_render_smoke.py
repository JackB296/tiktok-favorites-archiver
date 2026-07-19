"""Optional real-FFmpeg smoke check for the Story Builder render contract."""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import layout, stories, story_render, store


def test_real_ffmpeg_renders_a_small_personal_story_when_available():
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("SKIP real Story render (ffmpeg/ffprobe unavailable)")
        return
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(
        conn, 1, "https://example.test/1",
        favorited_at="2025-01-01", kind="video", status="done",
    )
    conn.execute(
        "UPDATE item SET duration_s = 0.8, has_audio = 1 WHERE id = 1"
    )
    conn.commit()
    story = stories.create_story(conn, {
        "name": "Smoke story",
        "description": "",
        "chapters": [{
            "item_id": 1,
            "title": "Color card",
            "start_s": 0.1,
            "end_s": 0.5,
        }],
    })

    with tempfile.TemporaryDirectory() as downloads:
        subprocess.run([
            "ffmpeg", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x6c5ce7:s=120x200:r=30:d=0.8",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.8",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", layout.movie(downloads, 1),
        ], check=True)
        rendered = story_render.render_story(conn, downloads, story["id"])
        target = layout.story_movie(downloads, story["id"])
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", target,
        ], check=True, capture_output=True, text=True)

        assert rendered["rendered_path"] == layout.story_relpath(story["id"])
        assert os.path.getsize(target) > 0
        assert 0.2 <= float(probe.stdout.strip()) <= 1.0


if __name__ == "__main__":
    import traceback

    try:
        test_real_ffmpeg_renders_a_small_personal_story_when_available()
        print("PASS test_real_ffmpeg_renders_a_small_personal_story_when_available")
    except Exception:
        print("FAIL test_real_ffmpeg_renders_a_small_personal_story_when_available")
        traceback.print_exc()
        raise SystemExit(1)
