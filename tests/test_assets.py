"""Tests for core.assets.save_assets — raw image + audio folder layout (stdlib)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import assets


def _touch(path, data=b"x"):
    with open(path, "wb") as f:
        f.write(data)


def test_save_assets_numbers_images_and_copies_audio():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src")
        dl = os.path.join(d, "downloads")
        os.makedirs(src)
        imgs = []
        for i in range(3):
            p = os.path.join(src, f"slide_{i}.jpg")
            _touch(p, bytes([i]))
            imgs.append(p)
        audio = os.path.join(src, "audio.mp3")
        _touch(audio, b"sound")

        folder = assets.save_assets(dl, 7, imgs, audio)
        assert folder == os.path.join(dl, "7")
        assert sorted(os.listdir(folder)) == ["01.jpg", "02.jpg", "03.jpg", "audio.mp3"]
        # Content preserved and in order.
        with open(os.path.join(folder, "02.jpg"), "rb") as f:
            assert f.read() == bytes([1])
        with open(os.path.join(folder, "audio.mp3"), "rb") as f:
            assert f.read() == b"sound"


def test_save_assets_without_audio():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src")
        os.makedirs(src)
        p = os.path.join(src, "slide_0.jpg")
        _touch(p)
        folder = assets.save_assets(d, 1, [p], audio_path=None)
        assert os.listdir(folder) == ["01.jpg"]


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
