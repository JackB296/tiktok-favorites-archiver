"""Tests for the Archive-item projection module (stdlib only)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store
from server.archive_items import ArchiveItems


def test_video_item_exposes_video_url():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/a", kind="video", status="done")
    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "1.mp4"), "w").close()
        d = ArchiveItems(conn, dl).get(1)
        assert d["video_url"] == "/media/1.mp4"
        assert d["images"] == [] and d["audio"] is None
        assert d["has_assets"] is False


def test_slideshow_item_lists_carousel_assets():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 2, "https://tiktok.com/b", kind="slideshow", status="done")
    store.set_has_assets(conn, 2, True)
    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "2.mp4"), "w").close()
        os.makedirs(os.path.join(dl, "2"))
        for name in ("01.jpg", "02.jpg", "audio.mp3"):
            open(os.path.join(dl, "2", name), "w").close()
        d = ArchiveItems(conn, dl).get(2)
        assert d["video_url"] == "/media/2.mp4"
        assert d["images"] == ["/media/2/01.jpg", "/media/2/02.jpg"]
        assert d["audio"] == "/media/2/audio.mp3"
        assert d["has_assets"] is True


def test_missing_media_yields_nulls():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 3, "https://tiktok.com/c", kind="unknown", status="pending")
    with tempfile.TemporaryDirectory() as dl:
        d = ArchiveItems(conn, dl).get(3)
        assert d["video_url"] is None and d["images"] == []


def test_list_applies_search_and_projects_public_items():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/cats")
    store.set_metadata(conn, 1, "cats", "alice")

    with tempfile.TemporaryDirectory() as dl:
        data = ArchiveItems(conn, dl).list(query="cats")

    assert [item["id"] for item in data] == [1]


def test_page_returns_latest_items_and_a_cursor():
    conn = store.init_db(store.connect(":memory:"))
    for item_id in range(1, 4):
        store.insert_item(conn, item_id, f"https://tiktok.com/{item_id}", status="done")

    with tempfile.TemporaryDirectory() as dl:
        page = ArchiveItems(conn, dl).page(limit=2, order="latest")

    assert [item["id"] for item in page["items"]] == [3, 2]
    assert page["next_cursor"] == 2


def test_page_shuffles_with_a_seed_and_keeps_the_cursor_contract():
    conn = store.init_db(store.connect(":memory:"))
    for item_id in range(1, 7):
        store.insert_item(conn, item_id, f"https://tiktok.com/{item_id}", status="done")

    with tempfile.TemporaryDirectory() as dl:
        items = ArchiveItems(conn, dl)
        first = items.page(limit=4, order="random", seed=21)
        second = items.page(limit=4, order="random", seed=21, cursor=first["next_cursor"])

    ids = [item["id"] for item in first["items"]] + [item["id"] for item in second["items"]]
    assert sorted(ids) == list(range(1, 7))
    assert first["next_cursor"] == first["items"][-1]["id"]
    assert second["next_cursor"] is None


def test_page_clamps_limit_so_the_cursor_stays_honest():
    conn = store.init_db(store.connect(":memory:"))
    for item_id in range(1, 102):
        store.insert_item(conn, item_id, f"https://tiktok.com/{item_id}", status="done")

    with tempfile.TemporaryDirectory() as dl:
        items = ArchiveItems(conn, dl)
        oversized = items.page(limit=500)   # store caps rows at 100
        tiny = items.page(limit=0)

    assert len(oversized["items"]) == 100
    assert oversized["next_cursor"] == oversized["items"][-1]["id"]  # not None
    assert len(tiny["items"]) == 1 and tiny["next_cursor"] == tiny["items"][0]["id"]


def test_item_projects_indexed_media_facts():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/1", kind="video", status="done")
    store.record_media_index(conn, 1, {"thumbnail_path": "x", "duration_s": 83.5, "width": 1080, "height": 1920, "codec": "h264", "file_size": 12_500_000}, "x")

    with tempfile.TemporaryDirectory() as dl:
        item = ArchiveItems(conn, dl).get(1)

    assert item["duration_s"] == 83.5
    assert item["media_width"] == 1080
    assert item["media_height"] == 1920
    assert item["media_codec"] == "h264"
    assert item["media_size"] == 12_500_000


def test_item_projects_the_last_recovery_error():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/1", status="failed")
    store.set_status(conn, 1, "failed", error="video download failed")

    with tempfile.TemporaryDirectory() as dl:
        item = ArchiveItems(conn, dl).get(1)

    assert item["status"] == "failed"
    assert item["error"] == "video download failed"


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
