"""Tests for shared Archive-media asset recovery."""
import os
import sys
import tempfile
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cobalt, media


Deps = namedtuple("Deps", "download_file save_assets default_audio")


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

    result = cobalt.Result("slideshow", None, ["one.jpg", "two.jpg"], "audio.mp3", None, "picker")
    deps = Deps(download_file, save_assets, "/default.mp3")

    with tempfile.TemporaryDirectory() as download_dir:
        value = media.recover_slideshow_assets(
            deps,
            download_dir,
            7,
            result,
            lambda images, audio: {"images": len(images), "audio": audio},
        )

    assert value == {"images": 2, "audio": saved["audio"]}
    assert saved["item_id"] == 7
    assert saved["image_count"] == 2


def test_recover_slideshow_assets_returns_none_when_no_images_download():
    result = cobalt.Result("slideshow", None, ["one.jpg"], None, None, "picker")
    deps = Deps(lambda url, path: False, lambda *args: None, "/default.mp3")

    with tempfile.TemporaryDirectory() as download_dir:
        assert media.recover_slideshow_assets(deps, download_dir, 7, result, lambda *_: "ready") is None


def test_resolve_default_audio_prefers_present_custom_track():
    with tempfile.TemporaryDirectory() as download_dir:
        # No custom file configured -> bundled default.
        assert media.resolve_default_audio(download_dir, None, "/bundled.mp3") == "/bundled.mp3"

        # Configured but the file is missing -> bundled default (graceful).
        assert media.resolve_default_audio(download_dir, "mine.mp3", "/bundled.mp3") == "/bundled.mp3"

        # Configured and present at the fixed path -> the custom track.
        custom = os.path.join(download_dir, media.CUSTOM_DEFAULT_AUDIO)
        os.makedirs(os.path.dirname(custom), exist_ok=True)
        with open(custom, "wb") as f:
            f.write(b"\x00")
        assert media.resolve_default_audio(download_dir, "mine.mp3", "/bundled.mp3") == custom


if __name__ == "__main__":
    test_recover_slideshow_assets_saves_raw_media_before_callback()
    test_recover_slideshow_assets_returns_none_when_no_images_download()
    test_resolve_default_audio_prefers_present_custom_track()
    print("PASS test_media")
