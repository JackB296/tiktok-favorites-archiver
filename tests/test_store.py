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


def test_favorite_order_is_independent_from_physical_archive_number():
    conn = _db()
    store.insert_item(conn, 120, "middle", favorite_order=2, status="done")
    store.insert_item(conn, 500, "newest", favorite_order=3, status="done")
    store.insert_item(conn, 300, "oldest", favorite_order=1, status="done")

    assert [row["id"] for row in store.page_items(conn, order="latest")] == [500, 120, 300]
    assert [row["id"] for row in store.page_items(conn, order="archive")] == [300, 120, 500]
    assert [row["id"] for row in store.window_items(conn, 120)] == [120, 300]


def test_feed_filter_skips_unready_rows_before_playable_archive_items():
    conn = _db()
    store.insert_item(conn, 10, "local", favorite_order=1, status="done")
    store.insert_item(conn, 20, "new-pending", favorite_order=2, status="pending")
    store.insert_item(conn, 21, "dead-original", favorite_order=3, status="expired")

    assert [row["id"] for row in store.page_items(conn, feed=True)] == [21, 10]


def test_upsert_uses_next_favorite_order_not_next_physical_id():
    conn = _db()
    store.insert_item(conn, 100, "old", favorite_order=1)

    new_id = store.upsert_link(conn, "new")

    assert new_id == 101
    assert store.get_item(conn, new_id)["favorite_order"] == 2


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


def test_reset_interrupted_downloads_requeues_stranded_items_as_failed():
    conn = _db()
    store.insert_item(conn, 1, "a")
    store.set_status(conn, 1, "downloading")
    store.insert_item(conn, 2, "b", status="done")

    assert store.reset_interrupted_downloads(conn) == 1

    row = store.get_item(conn, 1)
    assert row["status"] == "failed"
    assert "interrupted" in row["error"]
    assert store.get_item(conn, 2)["status"] == "done"  # finished items untouched
    assert store.reset_interrupted_downloads(conn) == 0  # clean DB is a no-op


def test_gallery_term_lists_round_trip_and_can_be_deleted():
    conn = _db()
    list_id = store.save_saved_list(conn, "gallery_term_list", "No FYP",
                                    {"mode": "exclude", "terms": ["#fyp", "for you"]})

    assert store.list_saved_lists(conn, "gallery_term_list") == [
        {"id": list_id, "name": "No FYP", "mode": "exclude", "terms": ["#fyp", "for you"]},
    ]
    assert store.delete_saved_list(conn, "gallery_term_list", list_id) is True
    assert store.list_saved_lists(conn, "gallery_term_list") == []


def test_playback_queues_round_trip_and_keep_selection_order():
    conn = _db()
    queue_id = store.save_saved_list(conn, "playback_queue", "Weekend games", {"item_ids": [9, 3, 7]})

    assert store.list_saved_lists(conn, "playback_queue") == [
        {"id": queue_id, "name": "Weekend games", "item_ids": [9, 3, 7]},
    ]
    assert store.delete_saved_list(conn, "playback_queue", queue_id) is True
    assert store.list_saved_lists(conn, "playback_queue") == []


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
        {"duration_s": 42.5, "width": 1080, "height": 1920, "codec": "h264", "file_size": 123, "has_audio": False, "thumbnail_path": ".archive/thumbnails/1.webp"},
        fingerprint="123:1000",
    )

    row = store.get_item(conn, 1)
    assert row["duration_s"] == 42.5
    assert row["thumbnail_path"] == ".archive/thumbnails/1.webp"
    assert row["has_audio"] == 0
    assert [item["id"] for item in store.items_needing_index(conn)] == []


def test_legacy_indexed_item_without_audio_facts_is_rechecked_without_losing_thumbnail():
    conn = _db()
    store.insert_item(conn, 1, "a", status="done")
    conn.execute("UPDATE item SET thumbnail_path = ? WHERE id = 1", (".archive/thumbnails/1.webp",))
    conn.commit()

    assert store.get_item(conn, 1)["has_audio"] is None
    assert [item["id"] for item in store.items_needing_index(conn)] == [1]


def test_page_items_sorts_confirmed_missing_audio_first_then_present_then_unknown():
    conn = _db()
    for item_id in range(1, 6):
        store.insert_item(conn, item_id, f"link{item_id}", status="done")
    conn.execute("UPDATE item SET has_audio = 0 WHERE id IN (2, 4)")
    conn.execute("UPDATE item SET has_audio = 1 WHERE id IN (1, 5)")
    conn.commit()

    first = store.page_items(conn, order="audio_missing", limit=3)
    second = store.page_items(conn, order="audio_missing", limit=3, cursor=first[-1]["id"])

    assert [row["id"] for row in first] == [4, 2, 5]
    assert [row["id"] for row in second] == [1, 3]


def test_page_items_filters_no_audio_including_silent_streams():
    conn = _db()
    for item_id in range(1, 7):
        store.insert_item(conn, item_id, f"link{item_id}", status="done")
    conn.execute("UPDATE item SET has_audio = 0 WHERE id IN (2, 4)")                    # no audio stream
    conn.execute("UPDATE item SET has_audio = 1, audio_silent = 0 WHERE id IN (1, 5)")  # audible
    conn.execute("UPDATE item SET has_audio = 1, audio_silent = 1 WHERE id = 6")        # stream, but silent
    conn.commit()  # id 3 stays NULL (unindexed / unknown)

    no_sound = store.page_items(conn, has_audio=False, order="latest")
    with_sound = store.page_items(conn, has_audio=True, order="latest")
    assert [row["id"] for row in no_sound] == [6, 4, 2]  # no-stream + silent-stream, newest first
    assert [row["id"] for row in with_sound] == [5, 1]   # only audible streams
    assert 3 not in [row["id"] for row in no_sound]      # unknown audio is not "no audio"


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


def test_set_active_run_state_refuses_to_leave_stopping():
    conn = _db()
    store.set_run_state(conn, state="stopping")
    assert store.set_active_run_state(conn, "paused") is False    # Pause must not cancel a Stop
    assert store.get_run_state(conn)["state"] == "stopping"
    assert store.set_active_run_state(conn, "running") is False   # nor a stale Continue
    assert store.get_run_state(conn)["state"] == "stopping"
    assert store.set_active_run_state(conn, "stopping") is True   # idempotent Stop stays allowed
    assert store.get_run_state(conn)["state"] == "stopping"


def test_page_items_matches_hashtags_authors_and_classifications():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", kind="video", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/b", kind="slideshow", status="pending")
    store.set_metadata(conn, 1, "cats are great #cats", "alice")
    store.set_metadata(conn, 2, "dogs everywhere #dogs", "bob")
    assert [r["id"] for r in store.page_items(conn, query="cats")] == [1]
    assert [r["id"] for r in store.page_items(conn, query="#dogs")] == [2]
    assert [r["id"] for r in store.page_items(conn, query="alice")] == [1]          # author match
    assert [r["id"] for r in store.page_items(conn, kinds=["slideshow"])] == [2]
    assert [r["id"] for r in store.page_items(conn, statuses=["done"])] == [1]
    assert sorted(r["id"] for r in store.page_items(conn)) == [1, 2]                # no filter


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

    preset_id = store.save_saved_list(conn, "gallery_preset", "Games without fyp",
                                      {"filters": {"include": "games", "exclude": "fyp", "kind": "video"}})

    assert store.list_saved_lists(conn, "gallery_preset") == [{
        "id": preset_id,
        "name": "Games without fyp",
        "filters": {"include": "games", "exclude": "fyp", "kind": "video"},
    }]
    assert store.delete_saved_list(conn, "gallery_preset", preset_id) is True
    assert store.list_saved_lists(conn, "gallery_preset") == []


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


def test_page_orders_use_indexes_not_temp_btree():
    conn = _db()
    keyed_orders = {
        "size_desc": "media_size", "duration_desc": "duration_s",
        "duration_asc": "duration_s", "favorite_date_desc": "favorited_at",
        "favorite_date_asc": "favorited_at", "attempts_desc": "attempt_count",
        "last_attempt_desc": "last_attempt_at", "author_asc": "author",
    }
    for order, field in keyed_orders.items():
        plan = "\n".join(
            row["detail"] for row in conn.execute(
                f"EXPLAIN QUERY PLAN SELECT * FROM item "
                f"WHERE {field} IS NOT NULL ORDER BY {field} DESC, id DESC LIMIT 50"
            )
        )
        assert "USE TEMP B-TREE" not in plan, f"{order}: {plan}"


def test_page_items_rejects_unknown_filter():
    conn = _db()
    store.insert_item(conn, 1, "a")
    try:
        store.page_items(conn, bogus_filter=1)
    except ValueError as e:
        assert "bogus_filter" in str(e)
    else:
        raise AssertionError("unknown page_items filter must be rejected")


def test_selectable_orders_match_page_orders():
    assert set(store.SELECTABLE_ORDERS) == (set(store._PAGE_ORDERS) - {"relevance"}) | {"random"}


def test_set_offloaded_marks_done_and_clears_failure_residue():
    conn = _db()
    store.insert_item(conn, 1, "a", status="failed")
    store.set_status(conn, 1, "failed", error="boom")
    store.insert_item(conn, 2, "b", status="done")
    store.record_archive_file_health(conn, [2])

    assert store.set_offloaded(conn, [1, 2]) == 2
    for item_id in (1, 2):
        row = store.get_item(conn, item_id)
        assert row["status"] == "done" and row["offloaded"] == 1
        assert row["error"] is None and row["archive_missing"] == 0
    assert store.set_offloaded(conn, [1, 2]) == 0  # already marked -> no change


def test_unmark_offloaded_clears_only_the_flag():
    conn = _db()
    store.insert_item(conn, 1, "a")
    store.set_offloaded(conn, [1])

    assert store.set_offloaded(conn, [1], offloaded=False) == 1
    row = store.get_item(conn, 1)
    assert row["offloaded"] == 0 and row["status"] == "done"  # status untouched
    assert store.set_offloaded(conn, [1], offloaded=False) == 0  # idempotent


def test_set_ignored_only_converts_pending_and_failed():
    conn = _db()
    store.insert_item(conn, 1, "a")                    # pending -> ignored
    store.insert_item(conn, 2, "b", status="failed")   # failed -> ignored
    store.insert_item(conn, 3, "c", status="done")     # untouched
    store.insert_item(conn, 4, "d", status="expired")  # untouched

    assert store.set_ignored(conn, [1, 2, 3, 4]) == 2
    assert store.get_item(conn, 1)["status"] == "ignored"
    assert store.get_item(conn, 2)["status"] == "ignored"
    assert store.get_item(conn, 3)["status"] == "done"
    assert store.get_item(conn, 4)["status"] == "expired"


def test_unignore_restores_pending():
    conn = _db()
    store.insert_item(conn, 1, "a")
    store.insert_item(conn, 2, "b", status="done")
    store.set_ignored(conn, [1])

    assert store.set_ignored(conn, [1, 2], ignored=False) == 1
    assert store.get_item(conn, 1)["status"] == "pending"
    assert store.get_item(conn, 2)["status"] == "done"  # never was ignored


def test_item_ids_in_range_respects_bounds():
    conn = _db()
    for n in (1, 2, 3, 5, 9):
        store.insert_item(conn, n, f"link{n}")
    assert store.item_ids_in_range(conn, 2, 5) == [2, 3, 5]
    assert store.item_ids_in_range(conn, 6, 8) == []


def test_item_ids_matching_agrees_with_page_items_and_rejects_paging():
    conn = _db()
    store.insert_item(conn, 1, "one", status="done")
    store.insert_item(conn, 2, "two", status="failed")
    store.insert_item(conn, 3, "three", status="failed")
    store.set_metadata(conn, 2, "#games clip", "alice")
    store.set_metadata(conn, 3, "#fyp clip", "bob")

    page_ids = sorted(
        row["id"] for row in store.page_items(conn, statuses=["failed"], exclude=["fyp"], limit=100)
    )
    assert store.item_ids_matching(conn, statuses=["failed"], exclude=["fyp"]) == page_ids == [2]
    for bad in ({"order": "archive"}, {"limit": 10}, {"cursor": 1}, {"seed": 7}, {"bogus": 1}):
        try:
            store.item_ids_matching(conn, **bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad} must be rejected")


def test_page_items_filters_by_offloaded_flag():
    conn = _db()
    store.insert_item(conn, 1, "a", status="done")
    store.insert_item(conn, 2, "b", status="done")
    store.set_offloaded(conn, [1])

    assert [row["id"] for row in store.page_items(conn, offloaded=True)] == [1]
    assert [row["id"] for row in store.page_items(conn, offloaded=False)] == [2]


def test_items_needing_index_skips_offloaded_items():
    conn = _db()
    store.insert_item(conn, 1, "a", status="done")
    store.insert_item(conn, 2, "b", status="done")
    store.set_offloaded(conn, [2])

    assert [row["id"] for row in store.items_needing_index(conn)] == [1]


def test_default_audio_defaults_to_bundled_and_sets_and_clears():
    conn = _db()
    assert store.get_library_settings(conn)["default_audio_name"] is None  # bundled by default

    store.set_default_audio(conn, "my-track.mp3")
    assert store.get_library_settings(conn)["default_audio_name"] == "my-track.mp3"

    store.set_default_audio(conn, None)
    assert store.get_library_settings(conn)["default_audio_name"] is None


def test_default_audio_column_migrates_onto_a_legacy_settings_table():
    conn = store.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE library_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            index_enabled INTEGER NOT NULL DEFAULT 1,
            thumbnail_width INTEGER NOT NULL DEFAULT 480,
            updated_at TEXT NOT NULL
        );
        INSERT INTO library_settings (id, index_enabled, thumbnail_width, updated_at)
        VALUES (1, 1, 480, '2020-01-01');
        """
    )
    conn.commit()
    store.init_db(conn)
    assert store.get_library_settings(conn)["default_audio_name"] is None
    store.set_default_audio(conn, "kept.mp3")
    assert store.get_library_settings(conn)["default_audio_name"] == "kept.mp3"


def test_get_items_and_get_songs_batch_lookups():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a")
    store.insert_item(conn, 3, "https://tiktok.com/c")
    song_id = store.upsert_song(conn, "shazam:1", "Track")

    items = store.get_items(conn, [3, 1, 3, 999])   # duplicates + missing ids
    assert sorted(items) == [1, 3]
    assert items[3]["link"] == "https://tiktok.com/c"
    assert store.get_items(conn, []) == {}

    songs = store.get_songs(conn, [song_id, song_id, 999])
    assert list(songs) == [song_id]
    assert songs[song_id]["title"] == "Track"
    assert store.get_songs(conn, []) == {}


def test_init_db_upgrades_a_pre_attempt_count_database():
    """Regression: SCHEMA's indexes reference the newest item columns, so an
    old database must get its column migrations BEFORE the schema script runs
    — otherwise init_db dies with "no such column: attempt_count"."""
    conn = store.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE item (
            id           INTEGER PRIMARY KEY,
            link         TEXT NOT NULL UNIQUE,
            favorited_at TEXT,
            kind         TEXT NOT NULL DEFAULT 'unknown',
            status       TEXT NOT NULL DEFAULT 'pending',
            has_assets   INTEGER NOT NULL DEFAULT 0,
            error        TEXT,
            caption      TEXT,
            author       TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        INSERT INTO item (id, link, status, created_at, updated_at)
        VALUES (1, 'https://tiktok.com/old', 'done', '2020-01-01', '2020-01-01');
        """
    )
    conn.commit()

    store.init_db(conn)  # must not raise

    row = store.get_item(conn, 1)
    assert row["status"] == "done"
    assert row["attempt_count"] == 0          # migrated column, defaulted
    assert row["favorite_order"] == 1         # backfilled from id
    assert [r["id"] for r in store.page_items(conn)] == [1]


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
