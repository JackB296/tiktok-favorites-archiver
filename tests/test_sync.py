"""Tests for core.sync — orchestration, status mapping, pause/stop.

Uses a fake Deps (no network/moviepy) and an in-memory DB, so it runs anywhere.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store, sync, cobalt


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
        counts = sync.run_sync(conn, dl, deps=_fake_deps(results), concurrency=1)
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
        sync.run_sync(conn, dl, deps=_fake_deps(results, download_ok=False), concurrency=1)
        assert store.get_item(conn, 1)["status"] == "failed"


def test_stop_halts_remaining_items():
    conn = store.init_db(store.connect(":memory:"))
    _seed(conn, ["a", "b", "c"])
    results = {k: cobalt.Result("video", "http://x/v.mp4", None, None, None, "tunnel") for k in ("a", "b", "c")}

    def progress(event):
        # After the first item completes, request a stop.
        store.set_run_state(conn, state="stopping")

    with tempfile.TemporaryDirectory() as dl:
        sync.run_sync(conn, dl, deps=_fake_deps(results), concurrency=1, progress=progress)
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
        sync.run_sync(conn, dl, deps=_fake_deps(results), concurrency=1, progress=progress, wait=wait)
    assert calls["waits"] >= 1                      # the pause gate was observed, then released
    assert store.get_item(conn, 1)["status"] == "done"
    assert store.get_item(conn, 2)["status"] == "done"


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
