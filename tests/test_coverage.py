import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import coverage, lens, store


def test_coverage_report_is_database_only_and_counts_repairable_gaps():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/1", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/2", status="done")
    conn.execute("UPDATE item SET source_info_status = 'ok' WHERE id = 1")
    conn.commit()
    report = coverage.report(conn)
    by_key = {entry["key"]: entry for entry in report["categories"]}
    assert by_key["source_metadata"]["ready"] == 1
    assert by_key["source_metadata"]["missing"] == 1
    assert by_key["comments"]["missing"] == 2
    assert report["total_items"] == 2


def test_coverage_counts_completed_local_lens_rows_as_ready():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/1", status="done")
    store.record_media_index(conn, 1, {
        "duration_s": 1.0, "width": 100, "height": 200, "codec": "h264",
        "file_size": 5, "thumbnail_path": ".archive/thumbnails/1.webp",
    }, "fingerprint")
    lens.replace_generated_source(conn, 1, "transcript", [], "fingerprint")
    lens.replace_generated_source(conn, 1, "ocr", [], "fingerprint")

    by_key = {entry["key"]: entry for entry in coverage.report(conn)["categories"]}

    assert by_key["transcripts"]["ready"] == 1
    assert by_key["transcripts"]["missing"] == 0
    assert by_key["ocr"]["ready"] == 1
    assert by_key["ocr"]["missing"] == 0


def test_thumbnail_coverage_excludes_offloaded_media_that_is_not_locally_indexable():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/1", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/2", status="done")
    store.record_media_index(conn, 1, {
        "duration_s": 1.0, "width": 100, "height": 200, "codec": "h264",
        "file_size": 5, "thumbnail_path": ".archive/thumbnails/1.webp",
    }, "fingerprint")
    store.set_offloaded(conn, [2])

    thumbnails = next(
        entry for entry in coverage.report(conn)["categories"]
        if entry["key"] == "thumbnails"
    )

    assert thumbnails["eligible"] == 1
    assert thumbnails["ready"] == 1
    assert thumbnails["missing"] == 0


def test_source_coverage_excludes_local_only_imports_without_a_remote_post():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/video/1", status="done")
    store.insert_item(conn, 2, "local://myfavett/2", status="done")

    by_key = {entry["key"]: entry for entry in coverage.report(conn)["categories"]}

    assert by_key["source_metadata"]["eligible"] == 1
    assert by_key["source_metadata"]["missing"] == 1
    assert by_key["comments"]["eligible"] == 1


def test_coverage_comment_repair_resumes_at_missing_items_without_refreshing_completed_snapshots():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/video/1", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/video/2", status="done")
    conn.execute(
        "UPDATE item SET source_info_status = 'ok', comments_status = 'ok' WHERE id = 1"
    )
    conn.commit()
    calls = []

    def extractor(link, include_comments=True):
        calls.append(link)
        return {"id": link.rsplit("/", 1)[-1], "title": "saved", "comments": []}

    from core import ytdlp_adapter
    real_extract = ytdlp_adapter.extract_post
    ytdlp_adapter.extract_post = extractor
    try:
        with tempfile.TemporaryDirectory() as downloads:
            result = coverage.run_repair(
                conn, downloads, targets=["source_metadata", "comments"],
            )
    finally:
        ytdlp_adapter.extract_post = real_extract

    assert result["source_metadata"] == {"completed": 1, "saved": 1, "unavailable": 0}
    assert calls == ["https://tiktok.com/video/2"]


def test_network_and_local_coverage_repairs_overlap_on_a_file_database():
    with tempfile.TemporaryDirectory() as directory:
        conn = store.init_db(store.connect(os.path.join(directory, "archive.db")))
        original_source = coverage.source_metadata.backfill
        original_index = coverage.indexer.index_pending_items
        calls = []

        def source(source_conn, _downloads, **_kwargs):
            calls.append(("source", source_conn is conn))
            time.sleep(0.15)
            return {"completed": 1, "saved": 1, "unavailable": 0}

        def index(_conn, _downloads, **_kwargs):
            calls.append(("index", False))
            time.sleep(0.15)
            return {"indexed": 1, "failed": 0}

        coverage.source_metadata.backfill = source
        coverage.indexer.index_pending_items = index
        try:
            started = time.perf_counter()
            result = coverage.run_repair(
                conn, directory, targets=["source_metadata", "thumbnails"],
            )
            elapsed = time.perf_counter() - started
        finally:
            coverage.source_metadata.backfill = original_source
            coverage.indexer.index_pending_items = original_index
            conn.close()

    assert result["source_metadata"]["saved"] == 1
    assert result["thumbnails"]["indexed"] == 1
    assert sorted(name for name, _same in calls) == ["index", "source"]
    assert ("source", False) in calls
    assert elapsed < 0.25


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
