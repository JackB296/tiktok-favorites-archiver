"""Tests for resumable Archive Gallery indexing."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import indexer, media_index, store


def test_index_pending_items_records_media_facts_once():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "a", status="done")
    calls = []

    with tempfile.TemporaryDirectory() as d:
        movie = os.path.join(d, "1.mp4")
        with open(movie, "wb") as f:
            f.write(b"movie")

        def inspect(download_dir, item_id, width):
            calls.append((item_id, width))
            return media_index.MediaIndex(12.0, 100, 200, "h264", 5, ".archive/thumbnails/1.webp")

        assert indexer.index_pending_items(conn, d, inspect=inspect, thumbnail_width=480) == {"indexed": 1, "failed": 0}
        assert indexer.index_pending_items(conn, d, inspect=inspect, thumbnail_width=480) == {"indexed": 0, "failed": 0}

    assert calls == [(1, 480)]
    assert store.get_item(conn, 1)["duration_s"] == 12.0


def test_rebuild_reindexes_existing_items_and_reports_progress():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "a", status="done")
    events = []

    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "1.mp4"), "wb") as f:
            f.write(b"movie")

        def inspect(_download_dir, _item_id, _width):
            return media_index.MediaIndex(12.0, 100, 200, "h264", 5, ".archive/thumbnails/1.webp")

        indexer.index_pending_items(conn, d, inspect=inspect)
        assert indexer.rebuild_index(conn, d, inspect=inspect, progress=events.append) == {"indexed": 1, "failed": 0}

    assert events == [
        {"event": "indexing", "indexed": 0, "failed": 0, "completed": 0, "total": 1},
        {"event": "indexing", "indexed": 1, "failed": 0, "completed": 1, "total": 1},
    ]
