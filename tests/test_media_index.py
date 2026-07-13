"""Tests for durable Archive-media inspection."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import media_index


class _Result:
    def __init__(self, payload):
        self.stdout = json.dumps(payload)


def test_inspect_media_reads_video_facts_and_file_size():
    payload = {
        "format": {"duration": "42.5"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "1.mp4")
        with open(path, "wb") as f:
            f.write(b"movie")

        facts = media_index.inspect_media(path, runner=lambda *_args, **_kwargs: _Result(payload))

    assert facts.duration_s == 42.5
    assert facts.width == 1080 and facts.height == 1920
    assert facts.codec == "h264"
    assert facts.file_size == 5
    assert facts.has_audio is True


def test_inspect_media_marks_video_without_an_audio_stream():
    payload = {
        "format": {"duration": "8"},
        "streams": [{"codec_type": "video", "codec_name": "h264", "width": 720, "height": 1280}],
    }
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "2.mp4")
        with open(path, "wb") as f:
            f.write(b"movie")

        facts = media_index.inspect_media(path, runner=lambda *_args, **_kwargs: _Result(payload))

    assert facts.has_audio is False


def test_index_media_uses_first_slideshow_image_as_thumbnail():
    calls = []
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "1"))
        image = os.path.join(d, "1", "01.jpg")
        with open(image, "wb") as f:
            f.write(b"image")

        result = media_index.index_media(
            d,
            1,
            thumbnail_width=480,
            inspect=lambda _path: media_index.MediaFacts(2.5, 100, 200, "h264", 5, True),
            make_thumbnail=lambda source, target, width: calls.append((source, target, width)),
        )

    assert result.thumbnail_path == ".archive/thumbnails/1.webp"
    assert result.has_audio is True
    assert calls[0][0] == image
    assert calls[0][2] == 480


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
