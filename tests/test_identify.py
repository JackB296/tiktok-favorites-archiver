"""Tests for core.identify — the pausable song-identification run.

Injected fakes stand in for ffmpeg (extractor), Shazam (identifier), and the
audio source, so the loop runs with no media, no network, and a no-op limiter.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store, identify, songid, cobalt


def _no_op_limiter():
    return cobalt.RateLimiter(1000, period=1000, now=lambda: 0.0, sleep=lambda s: None)


def _done_audio_item(conn, url):
    item_id = store.upsert_link(conn, url)
    store.set_status(conn, item_id, "done")
    conn.execute("UPDATE item SET has_audio = 1 WHERE id = ?", (item_id,))
    conn.commit()
    return item_id


def _fakes(mapping, raise_for=()):
    """Build (source, extractor, identifier) fakes driven by ``mapping``.

    ``source`` encodes the item id in its return; ``extractor`` writes that id
    into the clip file (or raises for ``raise_for`` ids); ``identifier`` reads
    the id back and returns the mapped SongMatch (or None).
    """
    seen_clips = []

    def source(download_dir, item_id):
        return f"src://{item_id}"

    def extractor(src, target):
        item_id = int(src.split("//")[1])
        if item_id in raise_for:
            raise RuntimeError("ffmpeg blew up")
        with open(target, "w") as f:
            f.write(str(item_id))
        return target

    def identifier(clip_path):
        seen_clips.append(clip_path)
        with open(clip_path) as f:
            item_id = int(f.read())
        return mapping.get(item_id)

    return source, extractor, identifier, seen_clips


def _match(title, artist="Artist", key=None):
    return songid.SongMatch(key=key, title=title, artist=artist)


def test_records_match_no_match_and_error():
    conn = store.init_db(store.connect(":memory:"))
    a = _done_audio_item(conn, "https://tiktok.com/a")
    b = _done_audio_item(conn, "https://tiktok.com/b")
    c = _done_audio_item(conn, "https://tiktok.com/c")

    source, extractor, identifier, _ = _fakes(
        {a: _match("Song A", key="k-a"), b: None}, raise_for={c},
    )
    n = identify.identify_items(conn, ".", identifier=identifier, source=source,
                                extractor=extractor, limiter=_no_op_limiter())

    assert n == 1
    ra = store.get_item(conn, a)
    assert ra["song_status"] == "identified" and ra["song_id"] is not None
    assert store.get_song(conn, ra["song_id"])["title"] == "Song A"
    assert store.get_item(conn, b)["song_status"] == "no_match"
    assert store.get_item(conn, c)["song_status"] == "error"
    assert "ffmpeg" in store.get_item(conn, c)["song_error"]


def test_shared_song_is_stored_once():
    conn = store.init_db(store.connect(":memory:"))
    a = _done_audio_item(conn, "https://tiktok.com/a")
    b = _done_audio_item(conn, "https://tiktok.com/b")
    shared = _match("Viral Sound", key="viral-1")

    source, extractor, identifier, _ = _fakes({a: shared, b: shared})
    identify.identify_items(conn, ".", identifier=identifier, source=source,
                            extractor=extractor, limiter=_no_op_limiter())

    assert conn.execute("SELECT COUNT(*) FROM song").fetchone()[0] == 1
    assert store.get_item(conn, a)["song_id"] == store.get_item(conn, b)["song_id"]


def test_progress_reports_initial_and_running_counts():
    conn = store.init_db(store.connect(":memory:"))
    a = _done_audio_item(conn, "https://tiktok.com/a")
    b = _done_audio_item(conn, "https://tiktok.com/b")
    events = []

    source, extractor, identifier, _ = _fakes({a: _match("A", key="a"), b: None})
    identify.identify_items(conn, ".", identifier=identifier, source=source,
                            extractor=extractor, limiter=_no_op_limiter(), progress=events.append)

    assert events[0] == {"event": "identification", "completed": 0, "total": 2,
                         "identified": 0, "no_match": 0, "errors": 0}
    assert events[-1]["completed"] == 2
    assert events[-1]["identified"] == 1
    assert events[-1]["no_match"] == 1
    assert events[-1]["errors"] == 0


def test_rerun_skips_already_identified():
    conn = store.init_db(store.connect(":memory:"))
    a = _done_audio_item(conn, "https://tiktok.com/a")
    b = _done_audio_item(conn, "https://tiktok.com/b")

    source, extractor, identifier, seen = _fakes({a: _match("A", key="a"), b: _match("B", key="b")})
    identify.identify_items(conn, ".", identifier=identifier, source=source,
                            extractor=extractor, limiter=_no_op_limiter())
    first_pass = len(seen)

    # Second pass: both are 'identified', so nothing is re-fetched.
    identify.identify_items(conn, ".", identifier=identifier, source=source,
                            extractor=extractor, limiter=_no_op_limiter())
    assert first_pass == 2
    assert len(seen) == 2  # unchanged — no new identifications


def test_run_identification_stops_between_items():
    conn = store.init_db(store.connect(":memory:"))
    a = _done_audio_item(conn, "https://tiktok.com/a")
    b = _done_audio_item(conn, "https://tiktok.com/b")
    store.set_run_state(conn, state="running", phase="identify")

    def source(download_dir, item_id):
        return f"src://{item_id}"

    def extractor(src, target):
        with open(target, "w") as f:
            f.write(src.split("//")[1])
        return target

    def identifier(clip_path):
        store.set_run_state(conn, state="stopping")  # request a stop mid-run
        with open(clip_path) as f:
            return _match(f"Song {f.read()}", key="one")

    identify.run_identification(conn, ".", identifier=identifier, source=source,
                                extractor=extractor, limiter=_no_op_limiter())

    assert store.get_item(conn, a)["song_status"] == "identified"
    assert store.get_item(conn, b)["song_status"] is None  # never reached


def test_temp_clip_is_removed():
    conn = store.init_db(store.connect(":memory:"))
    a = _done_audio_item(conn, "https://tiktok.com/a")

    source, extractor, identifier, seen = _fakes({a: _match("A", key="a")})
    identify.identify_items(conn, ".", identifier=identifier, source=source,
                            extractor=extractor, limiter=_no_op_limiter())

    assert seen and not os.path.exists(seen[0])  # clip cleaned up after use


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
