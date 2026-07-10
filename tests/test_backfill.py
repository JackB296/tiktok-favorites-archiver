"""Tests for core.sync backfill — asset recovery, skipping, resumability."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cobalt, runs, store, sync


def _fake_deps(results):
    def resolve(link):
        return results[link]

    def download_file(url, path):
        with open(path, "w") as f:
            f.write("x")
        return True

    def save_assets(download_dir, n, images, audio):
        d = os.path.join(download_dir, str(n))
        os.makedirs(d, exist_ok=True)
        for i, _src in enumerate(images, 1):
            open(os.path.join(d, f"{i:02d}.jpg"), "w").close()
        if audio:
            open(os.path.join(d, "audio.mp3"), "w").close()
        return d

    def build_slideshow(images, audio, out):  # unused by backfill
        return True

    return sync.Deps(resolve, download_file, build_slideshow, save_assets, "/default.mp3")


def _results():
    return {
        "v": cobalt.Result("video", "http://x/v.mp4", None, None, None, "tunnel"),
        "s": cobalt.Result("slideshow", None, ["http://x/1.jpg", "http://x/2.jpg"], "http://x/a.mp3", None, "picker"),
        "dead": cobalt.Result("error", None, None, None, "gone", "error"),
    }


def _seed(conn):
    store.upsert_link(conn, "v")       # 1 video
    store.upsert_link(conn, "s")       # 2 slideshow
    store.upsert_link(conn, "dead")    # 3 expired link
    store.insert_item(conn, 4, "local://file/4", status="done")  # synthetic -> skipped
    store.upsert_link(conn, "already")  # 5 already has assets
    store.set_has_assets(conn, 5, True)


def _run_backfill(conn, download_dir, **kwargs):
    return runs.execute(conn, "backfill", sync.run_backfill, download_dir, **kwargs)


def test_backfill_recovers_slideshow_assets_and_classifies():
    conn = store.init_db(store.connect(":memory:"))
    _seed(conn)
    with tempfile.TemporaryDirectory() as dl:
        result = _run_backfill(conn, dl, deps=_fake_deps(_results()), concurrency=1)
        assert store.get_item(conn, 1)["kind"] == "video" and store.get_item(conn, 1)["has_assets"] == 0
        assert store.get_item(conn, 2)["kind"] == "slideshow" and store.get_item(conn, 2)["has_assets"] == 1
        assert sorted(os.listdir(os.path.join(dl, "2"))) == ["01.jpg", "02.jpg", "audio.mp3"]
        assert store.get_item(conn, 3)["kind"] == "unresolved" and store.get_item(conn, 3)["has_assets"] == 0
        assert store.get_item(conn, 4)["kind"] == "unknown"   # local:// never resolved
        assert store.get_item(conn, 5)["has_assets"] == 1     # already had assets, untouched
        assert result["with_assets"] == 2                     # ids 2 and 5
    assert store.get_run_state(conn)["state"] == "idle"


def test_backfill_is_resumable():
    conn = store.init_db(store.connect(":memory:"))
    _seed(conn)
    with tempfile.TemporaryDirectory() as dl:
        _run_backfill(conn, dl, deps=_fake_deps(_results()), concurrency=1)
        # After a run, only the dead link still needs backfill (video classified,
        # slideshow has assets, local:// skipped, id5 already had assets).
        assert [r["id"] for r in sync.items_needing_backfill(conn)] == [3]


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
