"""yt-dlp fallback and TikTok comment-sidecar adapter behavior."""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import ytdlp_adapter


class Response:
    def __init__(self, data):
        self.data = data
    def raise_for_status(self):
        return None
    def json(self):
        return self.data


def _raw(comment_id, text, reply_id="0"):
    return {
        "cid": comment_id, "text": text, "reply_id": reply_id,
        "create_time": 100, "digg_count": 3,
        "user": {"uid": f"u-{comment_id}", "unique_id": f"handle-{comment_id}", "nickname": f"Name {comment_id}"},
    }


def test_comment_collection_paginates_top_level_and_complete_replies_without_duplicates():
    calls = []

    def get(url, params, headers, timeout):
        calls.append((url, dict(params)))
        if url.endswith("/reply/"):
            return Response({"comments": [_raw("r1", "reply one", "c1"), _raw("r2", "reply two", "c1")], "has_more": 0, "cursor": 2})
        if str(params["cursor"]) == "0":
            first = _raw("c1", "top one")
            first.update({"reply_comment_total": 2, "reply_comment": [_raw("r1", "reply one", "c1")]})
            return Response({"comments": [first], "has_more": 1, "cursor": 1})
        return Response({"comments": [_raw("c2", "top two")], "has_more": 0, "cursor": 2})

    comments = ytdlp_adapter.extract_comments("123", requester=get, limit=10)

    assert [comment["id"] for comment in comments] == ["c1", "r1", "r2", "c2"]
    assert comments[0]["parent"] == "root"
    assert comments[1]["parent"] == "c1" and comments[1]["author"] == "Name r1"
    assert len(calls) == 3


def test_default_comment_requester_reuses_the_worker_connection_pool():
    calls = []

    class Session:
        def get(self, url, params, headers, timeout):
            calls.append((url, dict(params)))
            return Response({"comments": [], "has_more": 0, "cursor": 0})

    session = Session()
    ytdlp_adapter._HTTP_LOCAL.session = session
    try:
        ytdlp_adapter.extract_comments("123", limit=10)
        ytdlp_adapter.extract_comments("456", limit=10)
    finally:
        del ytdlp_adapter._HTTP_LOCAL.session

    assert len(calls) == 2


def test_failed_comment_collection_stays_pending_instead_of_becoming_an_empty_snapshot():
    class YDL:
        def __init__(self, _options): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def extract_info(self, _link, download=False):
            return {"id": "123", "comment_count": 10}

    original = ytdlp_adapter.extract_comments
    ytdlp_adapter.extract_comments = lambda _post_id: (_ for _ in ()).throw(RuntimeError("blocked"))
    try:
        info = ytdlp_adapter.extract_post(
            "https://www.tiktok.com/@x/video/123",
            include_comments=True,
            ydl_class=YDL,
        )
    finally:
        ytdlp_adapter.extract_comments = original

    assert info["_comments_attempted"] is False
    assert "comments" not in info


def test_post_extractor_reuses_one_ytdlp_instance_per_worker_and_mode():
    created = []

    class YDL:
        def __init__(self, options):
            created.append(dict(options))

    ytdlp_adapter._YDL_LOCAL.instances = {}
    try:
        first = ytdlp_adapter._worker_ydl(YDL, {"getcomments": True})
        second = ytdlp_adapter._worker_ydl(YDL, {"getcomments": True})
        without_comments = ytdlp_adapter._worker_ydl(YDL, {"getcomments": False})
    finally:
        del ytdlp_adapter._YDL_LOCAL.instances

    assert first is second
    assert first is not without_comments
    assert len(created) == 2


def test_video_download_prefers_an_audible_h264_rendition_over_silent_1080p():
    class YDL:
        def __init__(self, options):
            self.options = options
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def download(self, _links):
            payload = b"audible-720" if "vcodec=h264" in self.options["format"] else b"silent-1080"
            path = self.options["outtmpl"].replace("%(ext)s", "mp4")
            with open(path, "wb") as output:
                output.write(payload)

    def inspect(path):
        audible = open(path, "rb").read().startswith(b"audible")
        return {
            "width": 720 if audible else 1080,
            "height": 1280 if audible else 1920,
            "has_audio": audible, "audio_silent": not audible,
        }

    with tempfile.TemporaryDirectory() as directory:
        destination = os.path.join(directory, "chosen.mp4")
        assert ytdlp_adapter.download_best_video(
            "https://tiktok/1", destination, ydl_class=YDL, inspect=inspect,
        ) is True
        assert open(destination, "rb").read() == b"audible-720"


def test_video_download_repairs_silent_high_resolution_video_with_synced_audio():
    class YDL:
        def __init__(self, options):
            self.options = options
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def download(self, _links):
            high_resolution = "vcodec=h264" not in self.options["format"]
            payload = b"silent-1080" if high_resolution else b"audible-720"
            path = self.options["outtmpl"].replace("%(ext)s", "mp4")
            with open(path, "wb") as output:
                output.write(payload)

    def inspect(path):
        payload = open(path, "rb").read()
        if payload == b"silent-1080":
            return {
                "duration_s": 12.0, "width": 1080, "height": 1920,
                "has_audio": True, "audio_silent": True,
            }
        if payload == b"audible-720":
            return {
                "duration_s": 12.1, "width": 720, "height": 1280,
                "has_audio": True, "audio_silent": False,
            }
        return {
            "duration_s": 12.0, "width": 1080, "height": 1920,
            "has_audio": True, "audio_silent": False,
        }

    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        high = open(command[command.index("-i") + 1], "rb").read()
        second_input = command.index("-i", command.index("-i") + 1)
        audio = open(command[second_input + 1], "rb").read()
        with open(command[-1], "wb") as output:
            output.write(b"repaired:" + high + b":" + audio)

    with tempfile.TemporaryDirectory() as directory:
        destination = os.path.join(directory, "chosen.mp4")
        assert ytdlp_adapter.download_best_video(
            "https://tiktok/1", destination, ydl_class=YDL,
            inspect=inspect, runner=run,
        ) is True
        assert open(destination, "rb").read().startswith(b"repaired:silent-1080:audible-720")

    assert commands[0][0] == "ffmpeg"
    assert commands[0][commands[0].index("-c:v") + 1] == "copy"


def test_real_ffmpeg_repair_preserves_higher_resolution_and_adds_audible_audio():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return
    with tempfile.TemporaryDirectory() as directory:
        high = os.path.join(directory, "high.mp4")
        audible = os.path.join(directory, "audible.mp4")
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=black:s=108x192:d=0.8", "-f", "lavfi", "-i",
            "anullsrc=r=44100:cl=stereo", "-shortest", "-c:v", "libx264",
            "-c:a", "aac", "-pix_fmt", "yuv420p", high,
        ], check=True)
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=black:s=72x128:d=0.8", "-f", "lavfi", "-i",
            "sine=frequency=880:duration=0.8", "-shortest", "-c:v", "libx264",
            "-c:a", "aac", "-pix_fmt", "yuv420p", audible,
        ], check=True)

        class YDL:
            def __init__(self, options): self.options = options
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def download(self, _links):
                source = audible if "vcodec=h264" in self.options["format"] else high
                shutil.copyfile(source, self.options["outtmpl"].replace("%(ext)s", "mp4"))

        destination = os.path.join(directory, "repaired.mp4")
        assert ytdlp_adapter.download_best_video(
            "https://tiktok/1", destination, ydl_class=YDL,
        ) is True
        from core.media_index import inspect_media
        facts = inspect_media(destination)
        assert (facts.width, facts.height) == (108, 192)
        assert facts.has_audio is True and facts.audio_silent is False


def test_video_download_checks_a_lower_resolution_when_the_same_codec_hd_copy_is_silent():
    attempted = []

    class YDL:
        def __init__(self, options): self.options = options
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def download(self, _links):
            selector = self.options["format"]
            attempted.append(selector)
            payload = b"audible-720" if "height<=720" in selector else b"silent-1080"
            with open(self.options["outtmpl"].replace("%(ext)s", "mp4"), "wb") as output:
                output.write(payload)

    def inspect(path):
        audible = open(path, "rb").read().startswith(b"audible")
        return {
            "duration_s": 10, "width": 720 if audible else 1080,
            "height": 1280 if audible else 1920,
            "has_audio": True, "audio_silent": not audible,
        }

    def run(command, **_kwargs):
        with open(command[-1], "wb") as output:
            output.write(b"repaired")

    with tempfile.TemporaryDirectory() as directory:
        assert ytdlp_adapter.download_best_video(
            "https://tiktok/1", os.path.join(directory, "out.mp4"),
            ydl_class=YDL, inspect=inspect, runner=run,
        ) is True

    assert any("height<=720" in selector for selector in attempted)


def test_accept_encoding_is_never_announced_to_tiktok():
    """TikTok serves a stub page to any request carrying Accept-Encoding, so
    yt-dlp's automatic header must be suppressed in every HTTP handler."""
    import importlib

    ytdlp_adapter.suppress_accept_encoding()

    patched = 0
    for name in ytdlp_adapter._HEADER_MODULES:
        try:
            module = importlib.import_module(f"yt_dlp.networking.{name}")
        except ImportError:
            continue
        headers = {"User-Agent": "test"}
        module.add_accept_encoding_header(headers, ["gzip", "br"])
        assert "Accept-Encoding" not in headers, f"{name} still announces an encoding"
        assert headers == {"User-Agent": "test"}, f"{name} altered the headers"
        patched += 1
    assert patched, "no yt-dlp HTTP handler was patched"

    # Safe to call again: the second pass must not wrap the stand-in twice.
    ytdlp_adapter.suppress_accept_encoding()
    module = importlib.import_module(f"yt_dlp.networking.{ytdlp_adapter._HEADER_MODULES[0]}")
    assert module.add_accept_encoding_header is ytdlp_adapter._keep_accept_encoding_off


if __name__ == "__main__":
    for test in (
        test_comment_collection_paginates_top_level_and_complete_replies_without_duplicates,
        test_default_comment_requester_reuses_the_worker_connection_pool,
        test_failed_comment_collection_stays_pending_instead_of_becoming_an_empty_snapshot,
        test_post_extractor_reuses_one_ytdlp_instance_per_worker_and_mode,
        test_video_download_prefers_an_audible_h264_rendition_over_silent_1080p,
        test_video_download_repairs_silent_high_resolution_video_with_synced_audio,
        test_real_ffmpeg_repair_preserves_higher_resolution_and_adds_audible_audio,
        test_video_download_checks_a_lower_resolution_when_the_same_codec_hd_copy_is_silent,
        test_accept_encoding_is_never_announced_to_tiktok,
    ):
        test()
        print(f"PASS {test.__name__}")
