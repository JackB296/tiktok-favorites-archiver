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


def test_measure_max_volume_reads_peak_and_returns_none_when_absent():
    class R:
        def __init__(self, stderr):
            self.stderr = stderr
    assert media_index.measure_max_volume_db("x", runner=lambda *_a, **_k: R("[volumedetect] max_volume: -3.2 dB\n")) == -3.2
    assert media_index.measure_max_volume_db("x", runner=lambda *_a, **_k: R("no volume line")) is None


def _audio_runner(payload, stderr):
    class R:
        def __init__(self, stdout=None, stderr=None):
            self.stdout = stdout
            self.stderr = stderr
    return lambda args, **_k: R(stdout=json.dumps(payload)) if args[0] == "ffprobe" else R(stderr=stderr)


def test_inspect_media_flags_a_silent_audio_stream():
    payload = {"format": {"duration": "5"}, "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 720, "height": 1280},
        {"codec_type": "audio", "codec_name": "aac"}]}
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "1.mp4")
        with open(path, "wb") as f:
            f.write(b"m")
        facts = media_index.inspect_media(path, runner=_audio_runner(payload, "max_volume: -91.0 dB"))
    assert facts.has_audio is True and facts.audio_silent is True


def test_inspect_media_treats_an_audible_stream_as_not_silent():
    payload = {"format": {"duration": "5"}, "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 720, "height": 1280},
        {"codec_type": "audio", "codec_name": "aac"}]}
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "1.mp4")
        with open(path, "wb") as f:
            f.write(b"m")
        facts = media_index.inspect_media(path, runner=_audio_runner(payload, "max_volume: -2.0 dB"))
    assert facts.has_audio is True and facts.audio_silent is False


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


def test_inspect_media_rejects_a_file_without_a_video_stream():
    payload = {"format": {"duration": "3"}, "streams": [{"codec_type": "audio"}]}
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "1.mp4")
        with open(path, "wb") as f:
            f.write(b"x")
        try:
            media_index.inspect_media(path, runner=lambda *_a, **_k: _Result(payload))
        except ValueError as error:
            assert "no video stream" in str(error)  # not an empty StopIteration
        else:
            raise AssertionError("expected ValueError")


class _ProbeResult:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def test_has_audio_stream_reads_the_ffprobe_stream_list():
    def fake_runner(cmd, **kwargs):
        assert cmd[0] == "ffprobe"
        assert "-select_streams" in cmd and cmd[cmd.index("-select_streams") + 1] == "a"
        return _ProbeResult(stdout='{"streams": [{"codec_type": "audio"}]}')

    assert media_index.has_audio_stream("/x/1.mp4", runner=fake_runner) is True


def test_has_audio_stream_is_false_on_probe_failure_bad_json_or_no_streams():
    assert media_index.has_audio_stream("/x/1.mp4", runner=lambda *a, **k: _ProbeResult(returncode=1)) is False
    assert media_index.has_audio_stream("/x/1.mp4", runner=lambda *a, **k: _ProbeResult(stdout="not json")) is False
    assert media_index.has_audio_stream("/x/1.mp4", runner=lambda *a, **k: _ProbeResult(stdout='{"streams": []}')) is False

    def exploding_runner(*_a, **_k):
        raise OSError("no ffprobe on PATH")

    assert media_index.has_audio_stream("/x/1.mp4", runner=exploding_runner) is False


def test_make_poster_builds_a_single_frame_jpeg_command():
    calls = []
    media_index.make_poster("/x/1.mp4", "/x/1.jpg.tmp", runner=lambda cmd, **k: calls.append((cmd, k)))
    cmd, kwargs = calls[0]
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-frames:v") + 1] == "1"
    assert cmd[cmd.index("-c:v") + 1] == "mjpeg"   # temp-suffix target needs explicit codec/muxer
    assert cmd[-1] == "/x/1.jpg.tmp"
    assert kwargs.get("check") is True


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
