"""Tests for core.sidecars — Plex/Kodi metadata sidecar generation (stdlib)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import sidecars, store


def _seed_done_item(conn, item_id, caption=None, author=None, favorited_at=None):
    store.insert_item(conn, item_id, f"https://tiktok.com/v/{item_id}", status="done", favorited_at=favorited_at)
    if caption or author:
        store.set_metadata(conn, item_id, caption=caption, author=author)


def test_nfo_escapes_metadata_and_falls_back_to_a_numbered_title():
    conn = store.init_db(store.connect(":memory:"))
    _seed_done_item(conn, 1, caption="cats & <dogs>", author="a<b>", favorited_at="2024-05-01 12:00:00")
    _seed_done_item(conn, 2)

    titled = sidecars.nfo_xml(store.get_item(conn, 1))
    untitled = sidecars.nfo_xml(store.get_item(conn, 2))

    assert "<title>cats &amp; &lt;dogs&gt;</title>" in titled
    assert "<studio>a&lt;b&gt;</studio>" in titled
    assert "<premiered>2024-05-01</premiered>" in titled
    assert "https://tiktok.com/v/1" in titled
    assert "<title>Favorite 2</title>" in untitled


def test_write_sidecars_creates_nfo_and_poster_for_finished_media_only():
    conn = store.init_db(store.connect(":memory:"))
    _seed_done_item(conn, 1, caption="hello")
    _seed_done_item(conn, 2)          # done, but no file on disk
    store.insert_item(conn, 3, "c")   # pending
    posters = []

    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "1.mp4"), "w").close()

        def make_poster(source, target):
            posters.append((source, target))
            open(target, "w").close()

        result = sidecars.write_sidecars(conn, dl, make_poster=make_poster)

        assert result == {"written": 1, "failed": 0}
        with open(os.path.join(dl, "1.nfo"), encoding="utf-8") as f:
            assert "<title>hello</title>" in f.read()
        assert posters == [(os.path.join(dl, "1.mp4"), os.path.join(dl, "1.jpg.tmp"))]
        assert os.path.exists(os.path.join(dl, "1.jpg"))       # published atomically
        assert not os.path.exists(os.path.join(dl, "1.jpg.tmp"))
        assert not os.path.exists(os.path.join(dl, "2.nfo"))


def test_poster_prefers_the_stored_thumbnail_and_is_not_regenerated():
    conn = store.init_db(store.connect(":memory:"))
    _seed_done_item(conn, 1, caption="x")
    store.record_media_index(
        conn, 1,
        {"thumbnail_path": ".archive/thumbnails/1.webp", "duration_s": 1.0,
         "width": 100, "height": 200, "codec": "h264", "file_size": 5},
        "fp",
    )
    posters = []

    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "1.mp4"), "w").close()
        os.makedirs(os.path.join(dl, ".archive/thumbnails"))
        open(os.path.join(dl, ".archive/thumbnails/1.webp"), "w").close()

        def make_poster(source, target):
            posters.append(source)
            open(target, "w").close()

        sidecars.write_sidecars(conn, dl, make_poster=make_poster)
        sidecars.write_sidecars(conn, dl, make_poster=make_poster)  # idempotent rerun

        assert posters == [os.path.join(dl, ".archive/thumbnails/1.webp")]
        assert os.path.exists(os.path.join(dl, "1.jpg"))
        assert os.path.exists(os.path.join(dl, "1.nfo"))  # nfo refreshed both times


def test_failures_are_counted_and_do_not_stop_the_run():
    conn = store.init_db(store.connect(":memory:"))
    _seed_done_item(conn, 1)
    _seed_done_item(conn, 2)
    events = []

    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "1.mp4"), "w").close()
        open(os.path.join(dl, "2.mp4"), "w").close()

        def make_poster(source, target):
            if "1.jpg" in target:
                raise RuntimeError("ffmpeg exploded")
            open(target, "w").close()

        result = sidecars.write_sidecars(conn, dl, progress=events.append, make_poster=make_poster)

    assert result == {"written": 1, "failed": 1}
    assert events[0] == {"event": "sidecars", "written": 0, "failed": 0, "completed": 0, "total": 2}
    assert events[-1] == {"event": "sidecars", "written": 1, "failed": 1, "completed": 2, "total": 2}


def test_stop_is_honored_between_items():
    conn = store.init_db(store.connect(":memory:"))
    for n in (1, 2, 3):
        _seed_done_item(conn, n)
    continues = iter([True, False])

    with tempfile.TemporaryDirectory() as dl:
        for n in (1, 2, 3):
            open(os.path.join(dl, f"{n}.mp4"), "w").close()

        result = sidecars.write_sidecars(
            conn, dl,
            should_continue=lambda: next(continues),
            make_poster=lambda source, target: open(target, "w").close(),
        )

    assert result == {"written": 1, "failed": 0}


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
