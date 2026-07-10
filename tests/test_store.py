"""Tests for core.store — SQLite schema + CRUD + run control (stdlib sqlite3)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store


def _db():
    conn = store.connect(":memory:")
    return store.init_db(conn)


def test_init_is_idempotent_and_seeds_run_state():
    conn = _db()
    store.init_db(conn)  # second call must not error or duplicate
    rs = store.get_run_state(conn)
    assert rs["state"] == "idle" and rs["concurrency"] == store.DEFAULT_CONCURRENCY


def test_insert_and_get_item():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", favorited_at="2021-01-01")
    row = store.get_item(conn, 1)
    assert row["id"] == 1 and row["link"] == "https://tiktok.com/a"
    assert row["status"] == "pending" and row["kind"] == "unknown" and row["has_assets"] == 0
    assert store.get_item_by_link(conn, "https://tiktok.com/a")["id"] == 1


def test_next_id_preserves_gaps():
    conn = _db()
    for n, link in ((1, "a"), (2, "b"), (5, "e")):
        store.insert_item(conn, n, link)
    assert store.next_item_id(conn) == 6  # max + 1, gaps preserved


def test_upsert_link_dedups_and_numbers():
    conn = _db()
    first = store.upsert_link(conn, "a", favorited_at="2020")
    again = store.upsert_link(conn, "a")               # same link -> same id
    second = store.upsert_link(conn, "b")              # new link -> next number
    assert first == 1 and again == 1 and second == 2
    assert store.counts_by_status(conn) == {"pending": 2}


def test_status_kind_assets_metadata_transitions():
    conn = _db()
    store.insert_item(conn, 1, "a")
    store.set_status(conn, 1, "downloading")
    store.set_kind(conn, 1, "slideshow")
    store.set_has_assets(conn, 1, True)
    store.set_metadata(conn, 1, caption="hi #cats", author="someone")
    row = store.get_item(conn, 1)
    assert row["status"] == "downloading" and row["kind"] == "slideshow"
    assert row["has_assets"] == 1 and row["caption"] == "hi #cats" and row["author"] == "someone"
    store.set_status(conn, 1, "failed", error="boom")
    assert store.get_item(conn, 1)["error"] == "boom"


def test_gallery_term_lists_round_trip_and_can_be_deleted():
    conn = _db()
    list_id = store.save_gallery_term_list(conn, "No FYP", "exclude", ["#fyp", "for you"])

    assert store.list_gallery_term_lists(conn) == [
        {"id": list_id, "name": "No FYP", "mode": "exclude", "terms": ["#fyp", "for you"]},
    ]
    assert store.delete_gallery_term_list(conn, list_id) is True
    assert store.list_gallery_term_lists(conn) == []


def test_playback_queues_round_trip_and_keep_selection_order():
    conn = _db()
    queue_id = store.save_playback_queue(conn, "Weekend games", [9, 3, 7])

    assert store.list_playback_queues(conn) == [
        {"id": queue_id, "name": "Weekend games", "item_ids": [9, 3, 7]},
    ]
    assert store.delete_playback_queue(conn, queue_id) is True
    assert store.list_playback_queues(conn) == []


def test_run_history_records_terminal_outcome_and_counts():
    conn = _db()
    run_id = store.start_run_history(conn, "sync")
    store.finish_run_history(conn, run_id, "completed", {"done": 12, "failed": 1})

    history = store.list_run_history(conn)
    assert history[0]["kind"] == "sync"
    assert history[0]["outcome"] == "completed"
    assert history[0]["counts"] == {"done": 12, "failed": 1}
    assert history[0]["finished_at"] is not None


def test_record_work_outcome_updates_lifecycle_fields_together():
    conn = _db()
    store.insert_item(conn, 1, "a")

    store.record_work_outcome(
        conn,
        1,
        {"status": "done", "kind": "slideshow", "has_assets": 1},
    )

    row = store.get_item(conn, 1)
    assert row["status"] == "done"
    assert row["kind"] == "slideshow"
    assert row["has_assets"] == 1
    assert row["error"] is None


def test_work_outcomes_count_attempts_and_record_the_latest_attempt_time():
    conn = _db()
    store.insert_item(conn, 1, "a")
    store.record_work_outcome(conn, 1, {"status": "failed", "kind": "unknown", "error": "timeout"})
    first = store.get_item(conn, 1)
    store.record_work_outcome(conn, 1, {"status": "done", "kind": "video"})
    second = store.get_item(conn, 1)

    assert first["attempt_count"] == 1 and first["last_attempt_at"]
    assert second["attempt_count"] == 2
    assert second["last_attempt_at"] >= first["last_attempt_at"]


def test_page_items_filters_and_sorts_by_download_attempts():
    conn = _db()
    for item_id in (1, 2, 3):
        store.insert_item(conn, item_id, f"link{item_id}")
    for _ in range(3):
        store.record_work_outcome(conn, 1, {"status": "failed", "kind": "unknown"})
    for _ in range(2):
        store.record_work_outcome(conn, 2, {"status": "failed", "kind": "unknown"})
    rows = store.page_items(conn, min_attempts=2, order="attempts_desc")
    assert [row["id"] for row in rows] == [1, 2]
    untouched = store.page_items(conn, max_attempts=0)
    assert [row["id"] for row in untouched] == [3]


def test_page_items_sorts_by_creator_and_latest_download_attempt_with_cursors():
    conn = _db()
    for item_id in (1, 2, 3):
        store.insert_item(conn, item_id, f"link{item_id}")
    store.set_metadata(conn, 1, "", "Zoe")
    store.set_metadata(conn, 2, "", "Ada")
    conn.execute("UPDATE item SET last_attempt_at = ? WHERE id = ?", ("2025-01-01T10:00:00", 1))
    conn.execute("UPDATE item SET last_attempt_at = ? WHERE id = ?", ("2025-01-02T10:00:00", 2))
    conn.commit()

    first_creator_page = store.page_items(conn, order="author_asc", limit=1)
    assert [row["id"] for row in first_creator_page] == [2]
    assert [row["id"] for row in store.page_items(conn, order="author_asc", cursor=2)] == [1]
    assert [row["id"] for row in store.page_items(conn, order="last_attempt_desc")] == [2, 1]


def test_record_asset_recovery_keeps_download_status():
    conn = _db()
    store.insert_item(conn, 1, "a", status="done")

    store.record_asset_recovery(conn, 1, {"kind": "slideshow", "has_assets": 1})

    row = store.get_item(conn, 1)
    assert row["status"] == "done"
    assert row["kind"] == "slideshow"
    assert row["has_assets"] == 1


def test_media_index_is_persisted_and_queryable():
    conn = _db()
    store.insert_item(conn, 1, "a", status="done")

    store.record_media_index(
        conn,
        1,
        {"duration_s": 42.5, "width": 1080, "height": 1920, "codec": "h264", "file_size": 123, "thumbnail_path": ".archive/thumbnails/1.webp"},
        fingerprint="123:1000",
    )

    row = store.get_item(conn, 1)
    assert row["duration_s"] == 42.5
    assert row["thumbnail_path"] == ".archive/thumbnails/1.webp"
    assert [item["id"] for item in store.items_needing_index(conn)] == []


def test_items_by_status_ordered():
    conn = _db()
    for n in (3, 1, 2):
        store.insert_item(conn, n, f"link{n}")
    store.set_status(conn, 2, "done")
    pending = store.items_by_status(conn, ["pending"])
    assert [r["id"] for r in pending] == [1, 3]  # ordered by id, excludes done


def test_run_state_updates():
    conn = _db()
    store.set_run_state(conn, state="running", phase="sync", concurrency=8, cobalt_url="http://cobalt:9000/")
    rs = store.get_run_state(conn)
    assert rs["state"] == "running" and rs["phase"] == "sync"
    assert rs["concurrency"] == 8 and rs["cobalt_url"] == "http://cobalt:9000/"


def test_search_items():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", kind="video", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/b", kind="slideshow", status="pending")
    store.set_metadata(conn, 1, "cats are great #cats", "alice")
    store.set_metadata(conn, 2, "dogs everywhere #dogs", "bob")
    assert [r["id"] for r in store.search_items(conn, query="cats")] == [1]
    assert [r["id"] for r in store.search_items(conn, query="#dogs")] == [2]
    assert [r["id"] for r in store.search_items(conn, query="alice")] == [1]        # author match
    assert [r["id"] for r in store.search_items(conn, kinds=["slideshow"])] == [2]
    assert [r["id"] for r in store.search_items(conn, statuses=["done"])] == [1]
    assert [r["id"] for r in store.search_items(conn)] == [1, 2]                     # no filter


def test_page_items_returns_latest_first_with_a_cursor():
    conn = _db()
    for item_id in range(1, 6):
        store.insert_item(conn, item_id, f"link{item_id}", status="done")

    first = store.page_items(conn, limit=2, order="latest")
    second = store.page_items(conn, limit=2, order="latest", cursor=first[-1]["id"])

    assert [row["id"] for row in first] == [5, 4]
    assert [row["id"] for row in second] == [3, 2]


def test_window_items_centers_a_favorite_with_older_neighbors():
    conn = _db()
    for item_id in range(1, 8):
        store.insert_item(conn, item_id, f"link{item_id}", status="done")

    rows = store.window_items(conn, 5, limit=3)

    assert [row["id"] for row in rows] == [5, 4, 3]


def test_playable_item_ids_return_finished_media_only():
    conn = _db()
    store.insert_item(conn, 1, "a", status="done")
    store.insert_item(conn, 2, "b", status="pending")

    assert store.playable_item_ids(conn) == [1]


def test_page_items_filters_duration_and_sorts_by_size():
    conn = _db()
    for item_id, size, duration in ((1, 10, 30), (2, 30, 10), (3, 20, 20)):
        store.insert_item(conn, item_id, f"link{item_id}", status="done")
        store.record_media_index(conn, item_id, {"thumbnail_path": "x", "duration_s": duration, "width": 1, "height": 1, "codec": "h264", "file_size": size}, "x")

    rows = store.page_items(conn, min_duration=15, order="size_desc")

    assert [row["id"] for row in rows] == [3, 1]


def test_page_items_keeps_size_order_across_cursor_pages():
    conn = _db()
    for item_id, size in ((1, 10), (2, 40), (3, 30), (4, 20)):
        store.insert_item(conn, item_id, f"link{item_id}", status="done")
        store.record_media_index(conn, item_id, {"thumbnail_path": "x", "duration_s": 1, "width": 1, "height": 1, "codec": "h264", "file_size": size}, "x")

    first = store.page_items(conn, order="size_desc", limit=2)
    second = store.page_items(conn, order="size_desc", limit=2, cursor=first[-1]["id"])

    assert [row["id"] for row in first] == [2, 3]
    assert [row["id"] for row in second] == [4, 1]


def test_page_items_random_order_pages_one_seeded_shuffle_without_repeats():
    conn = _db()
    for n in range(1, 9):
        store.insert_item(conn, n, f"link-{n}")
    first = store.page_items(conn, order="random", seed=7, limit=3)
    second = store.page_items(conn, order="random", seed=7, limit=10, cursor=first[-1]["id"])
    ids = [row["id"] for row in first] + [row["id"] for row in second]
    assert sorted(ids) == list(range(1, 9))  # every item exactly once across pages
    assert ids != list(range(1, 9)) and ids != list(range(8, 0, -1))  # shuffled
    assert [row["id"] for row in store.page_items(conn, order="random", seed=7, limit=10)] == ids
    reshuffled = [row["id"] for row in store.page_items(conn, order="random", seed=8, limit=10)]
    assert reshuffled != ids and sorted(reshuffled) == list(range(1, 9))


def test_page_items_random_order_paginates_to_completion_for_any_seed():
    conn = _db()
    for n in range(1, 13):
        store.insert_item(conn, n, f"link-{n}")
    for seed in (5, 8, 42, 99, 123456789, 2**31 - 1):
        seen, cursor = [], None
        for _ in range(10):  # 12 items at limit 5 must finish in 3 pages
            rows = store.page_items(conn, order="random", seed=seed, limit=5, cursor=cursor)
            seen += [row["id"] for row in rows]
            if len(rows) < 5:
                break
            cursor = rows[-1]["id"]
        assert sorted(seen) == list(range(1, 13)), (seed, seen)


def test_page_items_random_order_requires_a_seed():
    conn = _db()
    store.insert_item(conn, 1, "a")
    try:
        store.page_items(conn, order="random")
    except ValueError:
        pass
    else:
        raise AssertionError("random order without a seed must be rejected")


def test_page_items_applies_whitelist_blacklist_dates_and_media_filters():
    conn = _db()
    store.insert_item(conn, 1, "one", favorited_at="2025-01-10", kind="video", status="done")
    store.insert_item(conn, 2, "two", favorited_at="2025-02-10", kind="video", status="done")
    store.insert_item(conn, 3, "three", favorited_at="2025-03-10", kind="slideshow", status="failed")
    store.set_metadata(conn, 1, "#games highlight", "alice")
    store.set_metadata(conn, 2, "#fyp games", "bob")
    store.set_metadata(conn, 3, "#games", "alice")
    for item_id, duration, width, height, size in ((1, 25, 1080, 1920, 10), (2, 5, 1920, 1080, 30), (3, 40, 1000, 1000, 20)):
        store.record_media_index(conn, item_id, {"thumbnail_path": "x", "duration_s": duration, "width": width, "height": height, "codec": "h264", "file_size": size}, "x")

    rows = store.page_items(
        conn,
        statuses=["done"],
        min_duration=10,
        date_from="2025-01-01",
        date_to="2025-01-31",
        orientations=["portrait"],
        include=["games"],
        exclude=["fyp"],
    )

    assert [row["id"] for row in rows] == [1]


def test_library_index_settings_default_to_high_enabled():
    conn = _db()

    settings = store.get_library_settings(conn)

    assert settings["index_enabled"] == 1
    assert settings["thumbnail_width"] == 480


def test_library_index_status_reports_indexed_pending_and_failed_items():
    conn = _db()
    for item_id in range(1, 4):
        store.insert_item(conn, item_id, f"link{item_id}", status="done")
    store.record_media_index(conn, 1, {"thumbnail_path": "x", "duration_s": 1, "width": 1, "height": 1, "codec": "h264", "file_size": 1}, "x")
    store.record_media_index_error(conn, 3, "ffmpeg failed")

    assert store.library_index_status(conn) == {"total": 3, "indexed": 1, "pending": 2, "failed": 1}


def test_gallery_presets_round_trip_and_can_be_deleted():
    conn = _db()

    preset_id = store.save_gallery_preset(conn, "Games without fyp", {"include": "games", "exclude": "fyp", "kind": "video"})

    assert store.list_gallery_presets(conn) == [{
        "id": preset_id,
        "name": "Games without fyp",
        "filters": {"include": "games", "exclude": "fyp", "kind": "video"},
    }]
    assert store.delete_gallery_preset(conn, preset_id) is True
    assert store.list_gallery_presets(conn) == []


def test_page_items_searches_metadata_with_relevance_and_updates_index():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/@alice/video/1", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/@bob/video/2", status="done")
    store.insert_item(conn, 3, "https://tiktok.com/@carol/video/3", status="done")
    store.set_metadata(conn, 1, "#games games games speedrun", "alice")
    store.set_metadata(conn, 2, "#games speedrun", "bob")
    store.set_metadata(conn, 3, "cooking", "games curator")

    rows = store.page_items(conn, query="#games", limit=10)
    assert {row["id"] for row in rows} == {1, 2, 3}
    assert rows[0]["id"] == 1

    first = store.page_items(conn, query="games", limit=1)
    second = store.page_items(conn, query="games", limit=10, cursor=first[0]["id"])
    assert {row["id"] for row in [*first, *second]} == {1, 2, 3}

    store.set_metadata(conn, 2, "travel", "bob")
    assert [row["id"] for row in store.page_items(conn, query="games", limit=10)] == [1, 3]


def test_page_items_filters_media_codec_and_resolution_bounds():
    conn = _db()
    for item_id, codec, width, height in ((1, "h264", 1080, 1920), (2, "vp9", 1920, 1080), (3, "h264", 720, 1280)):
        store.insert_item(conn, item_id, f"link{item_id}", status="done")
        store.record_media_index(conn, item_id, {"thumbnail_path": "x", "duration_s": 1, "width": width, "height": height, "codec": codec, "file_size": 1}, "x")

    rows = store.page_items(conn, codecs=["h264"], min_width=1000, min_height=1500)

    assert [row["id"] for row in rows] == [1]


def test_page_items_filters_raw_assets_and_index_health():
    conn = _db()
    for item_id in range(1, 4):
        store.insert_item(conn, item_id, f"link{item_id}", status="done")
    store.set_has_assets(conn, 1, True)
    store.record_media_index(conn, 1, {"thumbnail_path": "x", "duration_s": 1, "width": 1, "height": 1, "codec": "h264", "file_size": 1}, "x")
    store.record_media_index_error(conn, 3, "ffprobe failed")

    assert [row["id"] for row in store.page_items(conn, has_assets=True)] == [1]
    assert [row["id"] for row in store.page_items(conn, index_state="missing")] == [2]
    assert [row["id"] for row in store.page_items(conn, index_state="failed")] == [3]


def test_library_statistics_summarize_indexed_archive_media():
    conn = _db()
    store.insert_item(conn, 1, "one", kind="video", status="done")
    store.insert_item(conn, 2, "two", kind="slideshow", status="done")
    store.insert_item(conn, 3, "three", kind="video", status="pending")
    store.record_media_index(conn, 1, {"thumbnail_path": "one", "duration_s": 60, "width": 1, "height": 1, "codec": "h264", "file_size": 100}, "one")
    store.record_media_index(conn, 2, {"thumbnail_path": "two", "duration_s": 90, "width": 1, "height": 1, "codec": "h264", "file_size": 200}, "two")

    assert store.library_statistics(conn) == {
        "favorites": 3, "ready": 2, "videos": 2, "slideshows": 1,
        "indexed": 2, "duration_s": 150.0, "media_size": 300,
    }


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
