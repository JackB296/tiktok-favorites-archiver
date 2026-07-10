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
