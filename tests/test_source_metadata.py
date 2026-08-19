"""Rich yt-dlp metadata persistence and portable source sidecars."""
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import source_metadata, store


def _info():
    return {
        "id": "1234567890",
        "webpage_url": "https://www.tiktok.com/@chef/video/1234567890",
        "title": "Short title",
        "description": "Full description #dinner",
        "timestamp": 1_720_000_000,
        "duration": 42.5,
        "width": 1080,
        "height": 1920,
        "uploader": "chef",
        "uploader_id": "9988",
        "uploader_url": "https://www.tiktok.com/@chef",
        "channel": "Chef Display",
        "channel_id": "channel-token",
        "view_count": 1200,
        "like_count": 110,
        "comment_count": 12,
        "repost_count": 8,
        "save_count": 25,
        "thumbnail": "https://cdn.example/cover.jpg",
        "formats": [{
            "format_id": "best", "width": 1080, "height": 1920,
            "vcodec": "h265", "acodec": "aac", "filesize": 1234,
            "url": "https://signed.example/video", "cookies": "secret=1",
        }],
        "subtitles": {"en": [{"ext": "vtt", "url": "https://cdn.example/en.vtt"}]},
        "comments": [{"id": "c1", "author": "Viewer", "author_username": "viewer", "text": "Great recipe", "like_count": 3}],
    }


def test_rich_metadata_updates_the_item_and_writes_private_free_sidecars():
    conn = store.init_db(store.connect(":memory:"))
    store.upsert_link(conn, "https://www.tiktok.com/@chef/video/1234567890")
    metadata = source_metadata.from_info(_info())

    with tempfile.TemporaryDirectory() as downloads:
        fetched = []

        def fetch(url, target):
            fetched.append((url, target))
            with open(target, "wb") as output:
                output.write(b"asset")
            return True

        source_metadata.archive(conn, downloads, 1, metadata, fetch=fetch)

        item = store.get_item(conn, 1)
        assert item["creator_username"] == "chef"
        assert item["author"] == "Chef Display"
        assert item["description"] == "Full description #dinner"
        assert item["source_width"] == 1080 and item["source_height"] == 1920
        assert item["view_count"] == 1200 and item["save_count"] == 25
        assert item["source_info_status"] == "ok"

        info_path = os.path.join(downloads, "1.info.json")
        assert os.path.isfile(info_path)
        saved = json.load(open(info_path, encoding="utf-8"))
        assert saved["description"] == "Full description #dinner"
        assert saved["comments"][0]["text"] == "Great recipe"
        assert saved["comments"][0]["author_username"] == "viewer"
        serialized = json.dumps(saved)
        assert "signed.example" not in serialized and "secret=1" not in serialized
        assert open(os.path.join(downloads, "1.description"), encoding="utf-8").read() == "Full description #dinner"
        assert json.load(open(os.path.join(downloads, "1.comments.json"), encoding="utf-8"))[0]["id"] == "c1"
        assert os.path.isfile(os.path.join(downloads, "1.source.jpg"))
        assert os.path.isfile(os.path.join(downloads, "1.en.vtt"))
        assert len(fetched) == 2


def test_automatic_captions_are_saved_and_image_pseudo_extensions_become_jpg():
    info = _info()
    info["thumbnail"] = "https://cdn.example/tos-maliva-p-0068/o123.image"
    info["subtitles"] = {}
    info["automatic_captions"] = {
        "en": [{"ext": "vtt", "url": "https://cdn.example/automatic.vtt"}],
    }
    metadata = source_metadata.from_info(info)

    with tempfile.TemporaryDirectory() as downloads:
        def fetch(_url, target):
            with open(target, "wb") as output:
                output.write(b"asset")
            return True

        source_metadata.write_sidecars(downloads, 1, metadata, fetch=fetch)

        assert os.path.isfile(os.path.join(downloads, "1.source.jpg"))
        assert os.path.isfile(os.path.join(downloads, "1.en.vtt"))


def test_explicit_failed_comment_attempt_is_not_treated_as_a_saved_empty_snapshot():
    info = _info()
    info.pop("comments")
    info["_comments_attempted"] = False
    metadata = source_metadata.from_info(info)
    assert metadata.comments == ()
    assert metadata.comments_attempted is False


def test_sidecar_assets_reuse_the_worker_connection_pool():
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def raise_for_status(self): return None
        def iter_content(self, _size): return [b"asset"]

    class Session:
        def get(self, url, stream, timeout):
            calls.append(url)
            return Response()

    source_metadata._HTTP_LOCAL.session = Session()
    try:
        with tempfile.TemporaryDirectory() as directory:
            assert source_metadata.fetch_resource("https://cdn.example/one", os.path.join(directory, "one"))
            assert source_metadata.fetch_resource("https://cdn.example/two", os.path.join(directory, "two"))
    finally:
        del source_metadata._HTTP_LOCAL.session

    assert calls == ["https://cdn.example/one", "https://cdn.example/two"]


def test_backfill_processes_existing_captioned_items_once_and_keeps_failures_retryable():
    conn = store.init_db(store.connect(":memory:"))
    store.upsert_link(conn, "https://www.tiktok.com/@chef/video/1234567890")
    store.set_metadata(conn, 1, "already captioned", "old display")
    store.upsert_link(conn, "https://www.tiktok.com/@gone/video/999")
    calls = []

    def extractor(link, include_comments=True):
        calls.append((link, include_comments))
        if link.endswith("/999"):
            raise RuntimeError("gone")
        return _info()

    with tempfile.TemporaryDirectory() as downloads:
        first = source_metadata.backfill(
            conn, downloads, extractor=extractor,
            fetch=lambda _url, _target: False,
        )
        second = source_metadata.backfill(
            conn, downloads, extractor=extractor,
            fetch=lambda _url, _target: False,
            recheck=True,
        )

    assert first == {"completed": 2, "saved": 1, "unavailable": 1}
    assert second == {"completed": 2, "saved": 1, "unavailable": 1}
    assert [link for link, _ in calls].count("https://www.tiktok.com/@chef/video/1234567890") == 2
    assert store.get_item(conn, 1)["description"] == "Full description #dinner"
    assert store.get_item(conn, 2)["source_info_status"] == "unavailable"


def test_single_post_refresh_catches_up_comments_the_bulk_backfill_would_skip():
    conn = store.init_db(store.connect(":memory:"))
    store.upsert_link(conn, "https://www.tiktok.com/@chef/video/1234567890")
    calls = []

    def extractor(link, include_comments=True):
        calls.append(link)
        info = _info()
        if len(calls) > 1:
            info["comments"] = list(info["comments"]) + [
                {"id": "c-new", "text": "posted since the last sync", "parent": "root"},
            ]
        return info

    with tempfile.TemporaryDirectory() as downloads:
        source_metadata.backfill(
            conn, downloads, extractor=extractor, fetch=lambda _url, _target: False,
        )
        # The ordinary chain has nothing left to do for this post...
        again = source_metadata.backfill(
            conn, downloads, extractor=extractor, fetch=lambda _url, _target: False,
        )
        assert again["completed"] == 0
        assert len(calls) == 1

        # ...but an explicit single-post refresh still goes and looks.
        source_metadata.refresh_item(
            conn, downloads, 1, extractor=extractor, fetch=lambda _url, _target: False,
        )

    assert len(calls) == 2
    snapshots = store.list_comment_snapshots(conn, 1)
    assert len(snapshots) == 2, "a refresh adds history rather than overwriting it"
    assert any(comment["text"] == "posted since the last sync" for comment in snapshots[0]["comments"])
    assert snapshots[0]["changes"]["added"] == 1

    try:
        source_metadata.refresh_item(conn, "downloads", 999)
    except KeyError:
        pass
    else:
        raise AssertionError("refreshing an unknown favorite was accepted")


def test_single_post_refresh_records_the_failure_and_reraises():
    conn = store.init_db(store.connect(":memory:"))
    store.upsert_link(conn, "https://www.tiktok.com/@gone/video/999")

    def extractor(_link, include_comments=True):
        raise RuntimeError("post is gone")

    with tempfile.TemporaryDirectory() as downloads:
        try:
            source_metadata.refresh_item(
                conn, downloads, 1, extractor=extractor, fetch=lambda _url, _target: False,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("a failed refresh reported success")

    assert store.get_item(conn, 1)["source_info_status"] == "unavailable"


def test_failed_refresh_never_downgrades_a_post_that_already_has_facts():
    conn = store.init_db(store.connect(":memory:"))
    store.upsert_link(conn, "https://www.tiktok.com/@chef/video/1234567890")
    calls = []

    def extractor(_link, include_comments=True):
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("TikTok said no this time")
        return _info()

    with tempfile.TemporaryDirectory() as downloads:
        source_metadata.backfill(
            conn, downloads, extractor=extractor, fetch=lambda _url, _target: False,
        )
        assert store.get_item(conn, 1)["source_info_status"] == "ok"
        try:
            source_metadata.refresh_item(
                conn, downloads, 1, extractor=extractor, fetch=lambda _url, _target: False,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("a failed refresh reported success")

    # The post keeps everything it already had, and its earlier snapshot.
    assert store.get_item(conn, 1)["source_info_status"] == "ok"
    assert len(store.list_comment_snapshots(conn, 1)) == 1


def test_archiving_refreshed_comments_keeps_history_and_publishes_empty_latest_copy():
    conn = store.init_db(store.connect(":memory:"))
    store.upsert_link(conn, "https://www.tiktok.com/@chef/video/1234567890")
    first_info = _info()
    second_info = _info()
    second_info["comments"] = []
    second_info["comment_count"] = 0

    with tempfile.TemporaryDirectory() as downloads:
        source_metadata.archive(conn, downloads, 1, source_metadata.from_info(first_info))
        source_metadata.archive(conn, downloads, 1, source_metadata.from_info(second_info))

        snapshots = store.list_comment_snapshots(conn, 1)
        assert len(snapshots) == 2
        assert snapshots[0]["comments"] == []
        assert snapshots[0]["changes"] == {"added": 0, "removed": 1, "changed": 0}
        assert json.load(open(os.path.join(downloads, "1.comments.json"), encoding="utf-8")) == []


def test_backfill_runs_slow_extraction_concurrently_without_losing_results():
    conn = store.init_db(store.connect(":memory:"))
    for item_id in range(1, 21):
        store.insert_item(conn, item_id, f"https://www.tiktok.com/@creator/video/{item_id}")

    lock = threading.Lock()
    active = 0
    peak = 0

    def extractor(link, include_comments=True):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.05)
            info = _info()
            info["id"] = link.rsplit("/", 1)[-1]
            return info
        finally:
            with lock:
                active -= 1

    with tempfile.TemporaryDirectory() as downloads:
        started = time.perf_counter()
        result = source_metadata.backfill(
            conn,
            downloads,
            extractor=extractor,
            fetch=lambda _url, _target: False,
            workers=4,
        )
        elapsed = time.perf_counter() - started

    assert result == {"completed": 20, "saved": 20, "unavailable": 0}
    assert peak == 4
    assert elapsed < 0.40
    assert conn.execute("SELECT COUNT(*) FROM item WHERE source_info_status = 'ok'").fetchone()[0] == 20


if __name__ == "__main__":
    for test in (
        test_rich_metadata_updates_the_item_and_writes_private_free_sidecars,
        test_automatic_captions_are_saved_and_image_pseudo_extensions_become_jpg,
        test_explicit_failed_comment_attempt_is_not_treated_as_a_saved_empty_snapshot,
        test_sidecar_assets_reuse_the_worker_connection_pool,
        test_backfill_processes_existing_captioned_items_once_and_keeps_failures_retryable,
        test_archiving_refreshed_comments_keeps_history_and_publishes_empty_latest_copy,
        test_backfill_runs_slow_extraction_concurrently_without_losing_results,
        test_single_post_refresh_catches_up_comments_the_bulk_backfill_would_skip,
        test_single_post_refresh_records_the_failure_and_reraises,
        test_failed_refresh_never_downgrades_a_post_that_already_has_facts,
    ):
        test()
        print(f"PASS {test.__name__}")
