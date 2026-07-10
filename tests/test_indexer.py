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


def test_parallel_indexing_covers_every_candidate_exactly_once():
    conn = store.init_db(store.connect(":memory:"))
    for n in range(1, 9):
        store.insert_item(conn, n, f"link-{n}", status="done")
    seen = []

    with tempfile.TemporaryDirectory() as d:
        for n in range(1, 9):
            with open(os.path.join(d, f"{n}.mp4"), "wb") as f:
                f.write(b"movie")

        def inspect(_download_dir, item_id, _width):
            seen.append(item_id)
            return media_index.MediaIndex(1.0, 100, 200, "h264", 5, f".archive/thumbnails/{item_id}.webp")

        result = indexer.index_pending_items(conn, d, inspect=inspect, workers=3)
        again = indexer.index_pending_items(conn, d, inspect=inspect, workers=3)

    assert result == {"indexed": 8, "failed": 0}
    assert again == {"indexed": 0, "failed": 0}
    assert sorted(seen) == list(range(1, 9))
    assert all(store.get_item(conn, n)["thumbnail_path"] for n in range(1, 9))


def test_parallel_indexing_stops_between_batches():
    conn = store.init_db(store.connect(":memory:"))
    for n in range(1, 7):
        store.insert_item(conn, n, f"link-{n}", status="done")
    continues = iter([True, False])  # allow batch 1, stop before batch 2

    with tempfile.TemporaryDirectory() as d:
        for n in range(1, 7):
            with open(os.path.join(d, f"{n}.mp4"), "wb") as f:
                f.write(b"movie")

        def inspect(_download_dir, item_id, _width):
            return media_index.MediaIndex(1.0, 100, 200, "h264", 5, f".archive/thumbnails/{item_id}.webp")

        result = indexer.index_pending_items(
            conn, d, inspect=inspect, workers=2, should_continue=lambda: next(continues)
        )

    assert result == {"indexed": 2, "failed": 0}  # exactly one batch of two
    assert sum(1 for n in range(1, 7) if store.get_item(conn, n)["thumbnail_path"]) == 2


def test_parallel_indexing_records_failures_without_stopping():
    conn = store.init_db(store.connect(":memory:"))
    for n in range(1, 5):
        store.insert_item(conn, n, f"link-{n}", status="done")

    with tempfile.TemporaryDirectory() as d:
        for n in range(1, 5):
            with open(os.path.join(d, f"{n}.mp4"), "wb") as f:
                f.write(b"movie")

        def inspect(_download_dir, item_id, _width):
            if item_id == 2:
                raise RuntimeError("ffprobe exploded")
            return media_index.MediaIndex(1.0, 100, 200, "h264", 5, f".archive/thumbnails/{item_id}.webp")

        result = indexer.index_pending_items(conn, d, inspect=inspect, workers=2)

    assert result == {"indexed": 3, "failed": 1}
    assert store.get_item(conn, 2)["index_error"] == "ffprobe exploded"


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
