"""Tests for shared Archive-media asset recovery."""
import os
import sys
import tempfile
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import layout, media


Deps = namedtuple(
    "Deps", "download_file save_assets default_audio audio_sources fallback_fingerprints",
    defaults=(None, ()),
)


def test_recover_slideshow_assets_saves_raw_media_before_callback():
    saved = {}

    def download_file(url, path):
        with open(path, "w") as f:
            f.write(url)
        return True

    def save_assets(download_dir, item_id, images, audio):
        saved["item_id"] = item_id
        saved["image_count"] = len(images)
        saved["audio"] = audio

    deps = Deps(download_file, save_assets, "/default.mp3")

    with tempfile.TemporaryDirectory() as download_dir:
        value = media.recover_slideshow_assets(
            deps,
            download_dir,
            7,
            "https://tiktok/photo/1",
            ["one.jpg", "two.jpg"],
            "audio.mp3",
            lambda images, audio, source: {
                "images": len(images), "audio": audio, "source": source,
            },
        )

    assert value == {"images": 2, "audio": saved["audio"], "source": "original"}
    assert saved["item_id"] == 7
    assert saved["image_count"] == 2


def test_recover_slideshow_assets_returns_none_when_no_images_download():
    deps = Deps(lambda url, path: False, lambda *args: None, "/default.mp3")

    with tempfile.TemporaryDirectory() as download_dir:
        assert media.recover_slideshow_assets(
            deps, download_dir, 7, "https://tiktok/photo/1", ["one.jpg"], None,
            lambda *_: "ready",
        ) is None


def test_resolve_default_audio_prefers_present_custom_track():
    with tempfile.TemporaryDirectory() as download_dir:
        # No custom file configured -> bundled default.
        assert media.resolve_default_audio(download_dir, None, "/bundled.mp3") == "/bundled.mp3"

        # Configured but the file is missing -> bundled default (graceful).
        assert media.resolve_default_audio(download_dir, "mine.mp3", "/bundled.mp3") == "/bundled.mp3"

        # Configured and present at the fixed path -> the custom track.
        custom = layout.custom_default_audio(download_dir)
        os.makedirs(os.path.dirname(custom), exist_ok=True)
        with open(custom, "wb") as f:
            f.write(b"\x00")
        assert media.resolve_default_audio(download_dir, "mine.mp3", "/bundled.mp3") == custom


def test_acquire_audio_reports_a_substituted_default_as_fallback():
    """No route produces the post's sound -> the encoder still gets a track,
    but the caller is told it is not this favorite's audio."""
    deps = Deps(lambda url, path: False, lambda *args: None, "/default.mp3")

    with tempfile.TemporaryDirectory() as work:
        path, source = media.acquire_audio(
            deps, "https://tiktok/photo/1", "https://cdn/audio", os.path.join(work, "a.mp3"),
        )

    assert (path, source) == ("/default.mp3", "fallback")


def test_acquire_audio_uses_the_routed_fetch_when_backends_are_wired():
    """With audio backends available the multi-route fetcher decides, and a
    route that produces real audio is reported as the original."""
    calls = []

    class Sources:
        inspect_audio = None
        resolve_audio = None
        ytdlp_audio = None

        def download_file(self, url, path):
            calls.append(url)
            with open(path, "wb") as handle:
                handle.write(b"real audio bytes")
            return True

    sources = Sources()
    sources.download_file = sources.download_file
    deps = Deps(lambda url, path: False, lambda *args: None, "/default.mp3", sources, ())

    with tempfile.TemporaryDirectory() as work:
        path, source = media.acquire_audio(
            deps, "https://tiktok/photo/1", "https://cdn/audio", os.path.join(work, "a.mp3"),
        )
        assert os.path.basename(path) == "a.mp3"

    assert source == "original"
    assert calls == ["https://cdn/audio"]


if __name__ == "__main__":
    test_recover_slideshow_assets_saves_raw_media_before_callback()
    test_recover_slideshow_assets_returns_none_when_no_images_download()
    test_resolve_default_audio_prefers_present_custom_track()
    test_acquire_audio_reports_a_substituted_default_as_fallback()
    test_acquire_audio_uses_the_routed_fetch_when_backends_are_wired()
    print("PASS test_media")
