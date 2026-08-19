"""Tests for core.sidecars — Plex/Kodi metadata sidecar generation (stdlib)."""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import sidecars, source_metadata, store


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


def test_nfo_prefers_source_date_and_full_description():
    conn = store.init_db(store.connect(":memory:"))
    _seed_done_item(conn, 1, caption="short", favorited_at="2026-08-01 12:00:00")
    store.set_source_metadata(conn, 1, source_metadata.from_info({
        "id": "1", "title": "short",
        "description": "The full source description",
        "timestamp": 1_751_766_523,
        "uploader": "cook", "channel": "Cook",
        "duration": 12, "width": 1080, "height": 1920,
        "view_count": 1, "like_count": 2, "comment_count": 3,
        "repost_count": 4, "save_count": 5, "comments": [],
    }))

    value = sidecars.nfo_xml(store.get_item(conn, 1))

    assert "<premiered>2025-07-06</premiered>" in value
    assert "The full source description" in value


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


def test_sidecar_posters_keep_the_measured_worker_pool_busy():
    conn = store.init_db(store.connect(":memory:"))
    for item_id in range(1, 21):
        _seed_done_item(conn, item_id)
    lock = threading.Lock()
    active = 0
    peak = 0

    def make_poster(_source, target):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.05)
            open(target, "w").close()
        finally:
            with lock:
                active -= 1

    with tempfile.TemporaryDirectory() as downloads:
        for item_id in range(1, 21):
            open(os.path.join(downloads, f"{item_id}.mp4"), "w").close()
        started = time.perf_counter()
        result = sidecars.write_sidecars(
            conn, downloads, make_poster=make_poster, workers=4,
        )
        elapsed = time.perf_counter() - started

    assert result == {"written": 20, "failed": 0}
    assert peak == 4
    assert elapsed < 0.40


def test_sidecar_run_backfills_rich_source_data_for_existing_media():
    conn = store.init_db(store.connect(":memory:"))
    _seed_done_item(conn, 1, caption="old caption", author="old author")
    info = {
        "id": "1", "webpage_url": "https://tiktok.com/v/1",
        "title": "source title", "description": "complete description",
        "uploader": "handle", "channel": "Display", "duration": 9,
        "width": 720, "height": 1280, "comment_count": 4,
    }
    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "1.mp4"), "w").close()
        result = sidecars.run_sidecars(
            conn, dl,
            extractor=lambda _link, include_comments=True: info,
            fetch=lambda _url, _target: False,
            make_poster=lambda _source, target: open(target, "w").close(),
        )

        assert result["source_metadata"]["saved"] == 1
        assert result["media_server"] == {"written": 1, "failed": 0}
        assert os.path.isfile(os.path.join(dl, "1.info.json"))
        assert store.get_item(conn, 1)["creator_username"] == "handle"


def test_portable_embedding_is_opt_in_and_runs_inside_the_sidecar_phase():
    conn = store.init_db(store.connect(":memory:"))
    _seed_done_item(conn, 1, caption="portable")
    calls = []

    def embed(conn, download_dir, progress=None, should_continue=None):
        calls.append(download_dir)
        return {"embedded": 1, "skipped": 0, "failed": 0}

    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "1.mp4"), "w").close()
        common = {
            "extractor": lambda _link, include_comments=True: {
                "id": "1", "title": "portable", "comments": [],
            },
            "fetch": lambda _url, _target: False,
            "make_poster": lambda _source, target: open(target, "w").close(),
            "embed": embed,
        }
        disabled = sidecars.run_sidecars(conn, dl, **common)
        store.set_library_settings(conn, portable_metadata_enabled=True)
        enabled = sidecars.run_sidecars(conn, dl, **common)

    assert disabled["portable_media"]["enabled"] is False
    assert enabled["portable_media"] == {
        "enabled": True, "embedded": 1, "skipped": 0, "failed": 0,
    }
    assert calls == [dl]


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
