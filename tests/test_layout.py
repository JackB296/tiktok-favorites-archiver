"""Tests for core.layout — the Archive-media path vocabulary (stdlib)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import layout


def test_per_favorite_paths_derive_from_the_archive_number():
    assert layout.movie("/dl", 7) == os.path.join("/dl", "7.mp4")
    assert layout.movie_name(7) == "7.mp4"
    assert layout.assets_dir("/dl", 7) == os.path.join("/dl", "7")
    assert layout.slideshow_audio("/dl", 7) == os.path.join("/dl", "7", "audio.mp3")
    assert layout.nfo("/dl", 7) == os.path.join("/dl", "7.nfo")
    assert layout.poster("/dl", 7) == os.path.join("/dl", "7.jpg")


def test_app_state_paths_live_under_dot_archive():
    assert layout.thumbnail_relpath(7) == ".archive/thumbnails/7.webp"
    assert layout.thumbnails_dir("/dl") == os.path.join("/dl", ".archive", "thumbnails")
    assert layout.custom_thumbnail_relpath(7, "png") == ".archive/custom-thumbnails/7.png"
    assert layout.replaced_movie("/dl", 7) == os.path.join("/dl", ".archive", "replaced", "7.mp4")
    assert layout.uploads_dir("/dl") == os.path.join("/dl", ".archive", "uploads")
    assert layout.custom_default_audio("/dl") == os.path.join("/dl", ".archive", "default-audio.mp3")


def test_private_relpaths_are_denied_case_insensitively():
    assert layout.is_private_relpath(".archive/uploads/x.upload") is True
    assert layout.is_private_relpath(".archive/replaced/1.mp4") is True
    assert layout.is_private_relpath(".ARCHIVE/Replaced/1.mp4") is True   # macOS case-insensitive FS
    assert layout.is_private_relpath(".archive/thumbnails/1.webp") is False
    assert layout.is_private_relpath("1.mp4") is False


def test_finished_movie_names_exclude_crashed_encode_temps():
    assert layout.is_finished_movie_name("12.mp4") is True
    assert layout.is_finished_movie_name("12.mp4.part.mp4") is False  # crashed encode
    assert layout.is_finished_movie_name("12.mp4.part") is False      # crashed download
    assert layout.is_finished_movie_name("12.part.mp4") is False
    assert layout.is_finished_movie_name("notes.mp4") is False
    assert layout.is_finished_movie_name("12.nfo") is False


def test_finished_movie_ids_sorts_numerically():
    names = ["10.mp4", "2.mp4", "1.mp4", "2.mp4.part.mp4", "cover.jpg", "3.nfo"]
    assert layout.finished_movie_ids(names) == [1, 2, 10]


def test_slideshow_images_lists_only_image_files_sorted():
    with tempfile.TemporaryDirectory() as dl:
        raw = os.path.join(dl, "7")
        os.makedirs(raw)
        for name in ("02.jpg", "01.jpg", "audio.mp3", "03.webp", "notes.txt"):
            open(os.path.join(raw, name), "w").close()
        assert layout.slideshow_images(dl, 7) == ["01.jpg", "02.jpg", "03.webp"]
        assert layout.slideshow_images(dl, 8) == []  # no assets folder


def test_source_audio_prefers_preserved_slideshow_audio():
    with tempfile.TemporaryDirectory() as dl:
        assert layout.source_audio(dl, 7) == layout.movie(dl, 7)
        os.makedirs(os.path.join(dl, "7"))
        audio = os.path.join(dl, "7", "audio.mp3")
        open(audio, "w").close()
        assert layout.source_audio(dl, 7) == audio


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
