"""Tests for core.sync — orchestration, status mapping, pause/stop.

Uses a fake Deps (no network/moviepy) and an in-memory DB, so it runs anywhere.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cobalt, runs, store, sync


def _fake_deps(results, download_ok=True, encode_ok=True):
    def resolve(link):
        return results[link]

    def download_file(url, path):
        with open(path, "w") as f:
            f.write("data")
        return download_ok

    def build_slideshow(images, audio, out):
        if encode_ok:
            with open(out, "w") as f:
                f.write("video")
        return encode_ok

    def save_assets(download_dir, n, images, audio):
        d = os.path.join(download_dir, str(n))
        os.makedirs(d, exist_ok=True)
        return d

    return sync.Deps(resolve, download_file, build_slideshow, save_assets, "/default.mp3")


def _seed(conn, links):
    for link in links:
        store.upsert_link(conn, link)


def _run_sync(conn, download_dir, **kwargs):
    kwargs.setdefault("indexer", lambda *_args, **_kwargs: {"indexed": 0, "failed": 0})
    return runs.execute(conn, "sync", sync.run_sync, download_dir, **kwargs)


def test_full_drain_status_mapping():
    conn = store.init_db(store.connect(":memory:"))
    results = {
        "v": cobalt.Result("video", "http://x/v.mp4", None, None, None, "tunnel"),
        "s": cobalt.Result("slideshow", None, ["http://x/1.jpg", "http://x/2.jpg"], "http://x/a.mp3", None, "picker"),
        "e": cobalt.Result("error", None, None, None, "gone", "error"),
        "u": cobalt.Result("unsupported", None, None, None, "no photo", "picker"),
        "t": cobalt.Result("transient", None, None, None, "HTTP 500", "500"),
    }
    _seed(conn, ["v", "s", "e", "u", "t"])  # ids 1..5
    with tempfile.TemporaryDirectory() as dl:
        counts = _run_sync(conn, dl, deps=_fake_deps(results), concurrency=1)
        assert store.get_item(conn, 1)["status"] == "done"      # video
        assert store.get_item(conn, 2)["status"] == "done"      # slideshow
        assert store.get_item(conn, 2)["has_assets"] == 1
        assert os.path.isdir(os.path.join(dl, "2"))             # raw assets saved
        assert store.get_item(conn, 3)["status"] == "expired"   # Cobalt error
        assert store.get_item(conn, 4)["status"] == "skipped"   # unsupported
        assert store.get_item(conn, 5)["status"] == "failed"    # transient (retryable)
        assert counts.get("done") == 2
    assert store.get_run_state(conn)["state"] == "idle"


def test_video_download_failure_is_retryable():
    conn = store.init_db(store.connect(":memory:"))
    _seed(conn, ["v"])
    results = {"v": cobalt.Result("video", "http://x/v.mp4", None, None, None, "tunnel")}
    with tempfile.TemporaryDirectory() as dl:
        _run_sync(conn, dl, deps=_fake_deps(results, download_ok=False), concurrency=1)
        assert store.get_item(conn, 1)["status"] == "failed"


def test_items_stranded_downloading_by_a_crash_are_retried_on_the_next_run():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "v", status="downloading")  # orphaned by a hard kill
    results = {"v": cobalt.Result("video", "http://x/v.mp4", None, None, None, "tunnel")}
    with tempfile.TemporaryDirectory() as dl:
        _run_sync(conn, dl, deps=_fake_deps(results), concurrency=1)
    assert store.get_item(conn, 1)["status"] == "done"  # reset + retried in the same run


def test_expired_links_remain_as_archive_markers_and_are_not_retried():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "gone", status="expired")

    def should_not_resolve(_link):
        raise AssertionError("expired favorites must not be retried automatically")

    deps = sync.Deps(should_not_resolve, lambda *_args: True, lambda *_args: True, lambda *_args: None, "/default.mp3")
    with tempfile.TemporaryDirectory() as dl:
        _run_sync(conn, dl, deps=deps, concurrency=1)

    assert store.get_item(conn, 1)["status"] == "expired"


def test_slideshow_image_download_failure_keeps_its_specific_error():
    result = cobalt.Result("slideshow", None, ["http://x/1.jpg"], None, None, "picker")
    deps = _fake_deps({"s": result}, download_ok=False)

    with tempfile.TemporaryDirectory() as dl:
        outcome = sync.process_item(deps, dl, {"id": 1, "link": "s"})

    assert outcome["error"] == "all images failed"


def test_unexpected_item_error_is_recorded_as_retryable_failure():
    conn = store.init_db(store.connect(":memory:"))
    _seed(conn, ["broken"])

    def fail_to_resolve(_link):
        raise RuntimeError("resolver crashed")

    deps = sync.Deps(fail_to_resolve, lambda *_args: True, lambda *_args: True, lambda *_args: None, "/default.mp3")
    with tempfile.TemporaryDirectory() as dl:
        _run_sync(conn, dl, deps=deps, concurrency=1)

    item = store.get_item(conn, 1)
    assert item["status"] == "failed"
    assert item["error"] == "resolver crashed"
    assert store.get_run_state(conn)["state"] == "idle"


def test_pause_survives_the_indexing_phase_transition():
    """Entering the indexing phase must not overwrite a concurrent pause/stop."""
    conn = store.init_db(store.connect(":memory:"))
    store.set_run_state(conn, state="paused")
    seen = []

    def indexer(_conn, _directory, thumbnail_width, progress, should_continue):
        seen.append(store.get_run_state(conn)["state"])
        return {"indexed": 0, "failed": 0}

    with tempfile.TemporaryDirectory() as dl:
        sync.run_sync(conn, dl, deps=_fake_deps({}), concurrency=1, indexer=indexer)

    assert seen == ["paused"]
    assert store.get_run_state(conn)["phase"] == "indexing"


def test_sync_indexes_finished_media_by_default():
    conn = store.init_db(store.connect(":memory:"))
    _seed(conn, ["v"])
    result = cobalt.Result("video", "http://x/v.mp4", None, None, None, "tunnel")
    calls = []

    with tempfile.TemporaryDirectory() as dl:
        _run_sync(
            conn,
            dl,
            deps=_fake_deps({"v": result}),
            concurrency=1,
            indexer=lambda _conn, directory, thumbnail_width, **_kwargs: calls.append((directory, thumbnail_width)),
        )

    assert len(calls) == 1
    assert calls[0][1] == 480


def test_rebuild_index_uses_library_quality_and_reports_progress():
    conn = store.init_db(store.connect(":memory:"))
    store.set_library_settings(conn, thumbnail_width=320)
    calls, events = [], []

    def indexer(_conn, directory, thumbnail_width, progress, should_continue):
        calls.append((directory, thumbnail_width, should_continue()))
        progress({"event": "indexing", "indexed": 1, "failed": 0, "completed": 1, "total": 1})
        return {"indexed": 1, "failed": 0}

    with tempfile.TemporaryDirectory() as dl:
        result = runs.execute(conn, "index", sync.run_index, dl, indexer=indexer, progress=events.append)

    assert result == {"indexed": 1, "failed": 0}
    assert calls == [(dl, 320, True)]
    assert events == [{"event": "indexing", "indexed": 1, "failed": 0, "completed": 1, "total": 1}]
    assert store.get_run_state(conn)["state"] == "idle"


def test_stop_halts_remaining_items():
    conn = store.init_db(store.connect(":memory:"))
    _seed(conn, ["a", "b", "c"])
    results = {k: cobalt.Result("video", "http://x/v.mp4", None, None, None, "tunnel") for k in ("a", "b", "c")}

    def progress(event):
        # After the first item completes, request a stop.
        store.set_run_state(conn, state="stopping")

    with tempfile.TemporaryDirectory() as dl:
        _run_sync(conn, dl, deps=_fake_deps(results), concurrency=1, progress=progress)
    assert store.get_item(conn, 1)["status"] == "done"
    assert store.get_item(conn, 2)["status"] == "pending"   # never started
    assert store.get_item(conn, 3)["status"] == "pending"
    assert store.get_run_state(conn)["state"] == "stopped"


def test_pause_then_continue():
    conn = store.init_db(store.connect(":memory:"))
    _seed(conn, ["a", "b"])
    results = {k: cobalt.Result("video", "http://x/v.mp4", None, None, None, "tunnel") for k in ("a", "b")}

    calls = {"paused_once": False, "waits": 0}

    def progress(event):
        # Pause once, right after the first item finishes.
        if not calls["paused_once"]:
            calls["paused_once"] = True
            store.set_run_state(conn, state="paused")

    def wait():
        # Simulate the user pressing "continue".
        calls["waits"] += 1
        store.set_run_state(conn, state="running")

    with tempfile.TemporaryDirectory() as dl:
        _run_sync(conn, dl, deps=_fake_deps(results), concurrency=1, progress=progress, wait=wait)
    assert calls["waits"] >= 1                      # the pause gate was observed, then released
    assert store.get_item(conn, 1)["status"] == "done"
    assert store.get_item(conn, 2)["status"] == "done"


def test_items_needing_backfill_skips_offloaded_and_ignored_items():
    conn = store.init_db(store.connect(":memory:"))
    _seed(conn, ["a", "b", "c"])  # ids 1..3, kind unknown, no assets
    store.set_offloaded(conn, [1])
    store.set_ignored(conn, [2])

    assert [row["id"] for row in sync.items_needing_backfill(conn)] == [3]


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
