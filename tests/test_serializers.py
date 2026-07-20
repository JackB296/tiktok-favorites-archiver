"""Tests for the Archive-item projection module (stdlib only)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store
from server.archive_items import (
    ArchiveItems,
    gallery_preset_filters,
    parse_mark_request,
    parse_page_query,
    parse_saved_list,
    parse_song_match,
)


def test_video_item_exposes_video_url():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/a", kind="video", status="done")
    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "1.mp4"), "w").close()
        d = ArchiveItems(conn, dl).get(1)
        assert d["video_url"] == "/media/1.mp4"
        assert d["images"] == [] and d["audio"] is None
        assert d["has_assets"] is False
        assert d["has_audio"] is None
        assert d["audio_silent"] is None


def test_video_item_exposes_confirmed_missing_audio():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/a", kind="video", status="done")
    conn.execute("UPDATE item SET has_audio = 0 WHERE id = 1")
    conn.commit()

    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "1.mp4"), "w").close()
        item = ArchiveItems(conn, dl).get(1)

    assert item["has_audio"] is False and item["audio_silent"] is None


def test_video_item_exposes_a_silent_audio_stream():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/a", kind="video", status="done")
    conn.execute("UPDATE item SET has_audio = 1, audio_silent = 1 WHERE id = 1")
    conn.commit()

    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "1.mp4"), "w").close()
        item = ArchiveItems(conn, dl).get(1)

    assert item["has_audio"] is True and item["audio_silent"] is True


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


def test_gallery_page_omits_slideshow_assets_but_full_item_retains_them():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 2, "https://tiktok.com/b", kind="slideshow", status="done")
    store.set_has_assets(conn, 2, True)
    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "2.mp4"), "w").close()
        os.makedirs(os.path.join(dl, "2"))
        for name in ("01.jpg", "02.jpg", "audio.mp3"):
            open(os.path.join(dl, "2", name), "w").close()

        items = ArchiveItems(conn, dl)
        page_item = items.page(limit=1)["items"][0]
        full_item = items.get(2)

    assert page_item["images"] == [] and page_item["audio"] is None
    assert full_item["images"] == ["/media/2/01.jpg", "/media/2/02.jpg"]
    assert full_item["audio"] == "/media/2/audio.mp3"


def test_missing_media_yields_nulls():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 3, "https://tiktok.com/c", kind="unknown", status="pending")
    with tempfile.TemporaryDirectory() as dl:
        d = ArchiveItems(conn, dl).get(3)
        assert d["video_url"] is None and d["images"] == []


def test_page_applies_search_and_projects_public_items():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/cats")
    store.set_metadata(conn, 1, "cats", "alice")

    with tempfile.TemporaryDirectory() as dl:
        page = ArchiveItems(conn, dl).page(query="cats")

    assert [item["id"] for item in page["items"]] == [1]


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


def test_parse_page_query_maps_and_transforms_a_full_param_set():
    query = parse_page_query({
        "search": "cats", "kind": "video", "status": "done", "limit": "24",
        "cursor": "99", "order": "random", "seed": "7",
        "min_duration": "1.5", "max_duration": "30", "min_size": "10", "max_size": "20",
        "min_width": "100", "max_width": "200", "min_height": "300", "max_height": "400",
        "min_attempts": "0", "max_attempts": "5",
        "codec": "h264,hevc", "orientation": "portrait, square",
        "include": "games, retro", "exclude": "fyp",
        "date_from": "2025-01-01", "date_to": "2025-02-01",
        "assets": "with", "index_state": "indexed", "recovery": "true",
    })

    assert query == {
        "query": "cats", "kinds": ["video"], "statuses": ["done"], "limit": 24,
        "cursor": 99, "order": "random", "seed": 7,
        "min_duration": 1.5, "max_duration": 30.0, "min_size": 10, "max_size": 20,
        "min_width": 100, "max_width": 200, "min_height": 300, "max_height": 400,
        "min_attempts": 0, "max_attempts": 5,
        "codecs": ["h264", "hevc"], "orientations": ["portrait", "square"],
        "include": ["games", "retro"], "exclude": ["fyp"],
        "date_from": "2025-01-01", "date_to": "2025-02-01",
        "has_assets": True, "index_state": "indexed", "recovery": True,
    }


def test_parse_page_query_maps_assets_without_and_ignores_falsy_recovery():
    query = parse_page_query({"assets": "without", "audio": "without", "recovery": "false", "kind": ""})

    assert query == {"has_assets": False, "has_audio": False, "recovery": False, "kinds": None}


def test_parse_page_query_preserves_fastapi_boolean_vocabulary():
    for raw in ("1", "true", "yes", "on"):
        assert parse_page_query({"recovery": raw}) == {"recovery": True}
    for raw in ("0", "false", "no", "off"):
        assert parse_page_query({"recovery": raw}) == {"recovery": False}


def test_parse_page_query_rejects_unknown_params_and_bad_values():
    bad_requests = (
        {"bogus": "1"},                # unknown param
        {"limit": "abc"},              # bad int
        {"min_duration": "fast"},      # bad float
        {"assets": "sideways"},        # unknown assets value
        {"index_state": "weird"},      # unknown index state
        {"order": "upside_down"},      # unknown order
        {"order": "relevance"},        # internal order is not selectable
        {"order": "random"},           # random without a seed
        {"recovery": "sometimes"},     # invalid boolean
    )
    for params in bad_requests:
        try:
            parse_page_query(params)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{params} must be rejected")


def test_parse_page_query_maps_the_offloaded_filter():
    assert parse_page_query({"offloaded": "with"}) == {"offloaded": True}
    assert parse_page_query({"offloaded": "without"}) == {"offloaded": False}


def test_parse_page_query_maps_private_curation_filters():
    assert parse_page_query({
        "starred": "true", "private_tag": "  Cozy Food  ",
    }) == {
        "starred": True, "private_tag_key": "cozy food",
    }


def test_parse_saved_list_accepts_each_collection():
    """The four saved named-list collections validate through one parser.
    Previously these validators lived in api.py behind the FastAPI import and
    were untestable on the bare host."""
    assert parse_saved_list("gallery-presets", {"name": " Games ", "filters": {"search": "games"}}) == (
        "Games", {"filters": {"search": "games"}},
    )
    assert parse_saved_list("gallery-term-lists", {"name": "No FYP", "mode": "exclude",
                                                   "terms": [" #fyp ", "#fyp", "for you"]}) == (
        "No FYP", {"mode": "exclude", "terms": ["#fyp", "for you"]},  # stripped + deduped
    )
    assert parse_saved_list("playback-queues", {"name": "Weekend", "item_ids": [9, 3, 7]}) == (
        "Weekend", {"item_ids": [9, 3, 7]},
    )
    assert parse_saved_list("song-playlists", {"name": "Drive", "song_ids": [1, 2]}) == (
        "Drive", {"song_ids": [1, 2]},
    )


def test_parse_saved_list_rejects_bad_bodies():
    rejected = [
        ("gallery-presets", None),                                        # not an object
        ("gallery-presets", {"name": "", "filters": {}}),                 # empty name
        ("gallery-presets", {"name": "x" * 81, "filters": {}}),           # name too long
        ("gallery-presets", {"name": "ok", "filters": {"nope": "x"}}),    # unknown filter
        ("gallery-term-lists", {"name": "ok", "mode": "banish", "terms": ["a"]}),
        ("gallery-term-lists", {"name": "ok", "mode": "include", "terms": []}),
        ("gallery-term-lists", {"name": "ok", "mode": "include", "terms": [1]}),
        ("playback-queues", {"name": "ok", "item_ids": []}),
        ("playback-queues", {"name": "ok", "item_ids": [1, 1]}),          # duplicate
        ("playback-queues", {"name": "ok", "item_ids": [0]}),             # not positive
        ("playback-queues", {"name": "ok", "item_ids": [True]}),          # bool is not an ID
        ("song-playlists", {"name": "ok", "song_ids": ["1"]}),            # string is not an ID
    ]
    for resource, body in rejected:
        try:
            parse_saved_list(resource, body)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{resource} must reject {body!r}")


def test_parse_song_match_requires_string_fields():
    """Non-string fields once reached dedup_key's .strip() (AttributeError ->
    500) or sqlite as un-bindable values. Every field must be str-or-None."""
    fields = parse_song_match({"title": " Blinding Lights ", "artist": "The Weeknd", "key": "40522491"})
    assert fields["title"] == " Blinding Lights "  # preserved verbatim; dedup_key normalizes
    assert fields["artist"] == "The Weeknd"
    assert fields["album"] is None

    for bad in (
        None,                                    # not an object
        {"title": ""},                           # empty title
        {"title": "  "},                         # blank title
        {"title": 123},                          # non-string title
        {"title": "ok", "artist": {"x": 1}},     # non-string artist
        {"title": "ok", "key": 40522491},        # non-string key
        {"title": "ok", "spotify_url": ["x"]},   # non-string url
    ):
        try:
            parse_song_match(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"must reject {bad!r}")


def test_gallery_presets_accept_the_offloaded_filter():
    assert gallery_preset_filters({"offloaded": "with", "search": "games"}) == {
        "offloaded": "with",
        "search": "games",
    }


def test_gallery_presets_accept_the_audio_filter():
    assert gallery_preset_filters({"audio": "with"}) == {"audio": "with"}
    assert gallery_preset_filters({"audio": "without"}) == {"audio": "without"}


def test_gallery_presets_accept_every_field_the_gallery_sends():
    """Regression: Gallery's currentFilters() sends every key, empty string when
    unset (Gallery.tsx / types.ts GalleryPresetFilters). Validation runs before
    empties are dropped, so one missing allowlist entry fails EVERY preset save
    — the audio filter shipped without one."""
    snapshot = {
        "search": "cats", "kind": "video", "status": "done", "order": "latest",
        "minDuration": "1", "maxDuration": "60", "minSize": "1000", "maxSize": "5000000",
        "minWidth": "480", "maxWidth": "1920", "minHeight": "480", "maxHeight": "1920",
        "minAttempts": "1", "maxAttempts": "5", "recovery": False,
        "codec": "h264", "dateFrom": "2024-01-01", "dateTo": "2024-12-31",
        "orientation": "portrait", "assets": "with", "audio": "without",
        "offloaded": "with", "indexState": "indexed", "include": "a,b", "exclude": "c",
    }
    assert gallery_preset_filters(snapshot) == {k: v for k, v in snapshot.items() if v}

    unset = {key: False if key == "recovery" else "" for key in snapshot}
    assert gallery_preset_filters(unset) == {}


def test_public_projection_includes_the_offloaded_flag():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/a", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/b", status="done")
    store.set_offloaded(conn, [1])

    with tempfile.TemporaryDirectory() as dl:
        items = ArchiveItems(conn, dl)
        assert items.get(1)["offloaded"] is True
        assert items.get(2)["offloaded"] is False


def test_page_projection_agrees_with_the_per_item_path():
    """The batched page/window/selected projection (one listdir + one song
    query) must produce exactly what the per-item get() path produces."""
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/a", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/b", status="done")
    store.insert_item(conn, 3, "https://tiktok.com/c", status="pending")
    song_id = store.upsert_song(conn, "shazam:9", "Track", artist="Artist")
    store.set_item_song(conn, 2, song_id, source="auto")

    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "1.mp4"), "w").close()  # only Favorite 1 has media
        items = ArchiveItems(conn, dl)
        paged = items.page(limit=50)["items"]
        assert paged == [items.get(n) for n in (3, 2, 1)]  # latest-first
        by_id = {item["id"]: item for item in paged}
        assert by_id[1]["video_url"] is not None
        assert by_id[2]["video_url"] is None
        assert by_id[2]["song"]["title"] == "Track"
        assert items.selected([2, 1]) == [items.get(2), items.get(1)]


def test_public_projection_embeds_the_identified_song():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/a", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/b", status="done")
    song_id = store.upsert_song(conn, "shazam:1", "Blinding Lights", artist="The Weeknd",
                                spotify_url="https://open.spotify.com/track/x")
    store.set_item_song(conn, 1, song_id, source="auto")
    store.set_item_song_no_match(conn, 2)

    with tempfile.TemporaryDirectory() as dl:
        items = ArchiveItems(conn, dl)
        one = items.get(1)
        assert one["song"]["title"] == "Blinding Lights"
        assert one["song"]["artist"] == "The Weeknd"
        assert one["song"]["spotify_url"].endswith("/x")
        assert one["song_status"] == "identified" and one["song_source"] == "auto"

        two = items.get(2)
        assert two["song"] is None
        assert two["song_status"] == "no_match"


def test_parse_mark_request_accepts_each_selector():
    assert parse_mark_request({"action": "offload", "ids": [1, 2]}) == ("offload", "ids", [1, 2], False)
    assert parse_mark_request({"action": "unoffload", "range": {"first_id": 1, "last_id": 9}}) == (
        "unoffload", "range", {"first_id": 1, "last_id": 9}, False,
    )
    action, kind, value, dry_run = parse_mark_request(
        {"action": "ignore", "filter": {"status": "failed"}, "dry_run": True}
    )
    assert (action, kind, dry_run) == ("ignore", "filter", True)
    assert value == {"statuses": ["failed"]}
    assert parse_mark_request({"action": "unignore", "ids": [7]}) == ("unignore", "ids", [7], False)


def test_parse_mark_request_rejects_bad_bodies():
    bad_bodies = (
        [],                                                    # not an object
        {"action": "explode", "ids": [1]},                     # unknown action
        {"ids": [1]},                                          # missing action
        {"action": "offload"},                                 # zero selectors
        {"action": "offload", "ids": [1], "range": {"first_id": 1, "last_id": 2}},  # two selectors
        {"action": "offload", "ids": []},                      # empty ids
        {"action": "offload", "ids": list(range(1, 102))},     # too many ids
        {"action": "offload", "ids": [0]},                     # non-positive id
        {"action": "offload", "ids": ["1"]},                   # non-int id
        {"action": "offload", "range": {"first_id": 5, "last_id": 2}},  # inverted range
        {"action": "offload", "range": {"first_id": 1}},       # missing bound
        {"action": "offload", "filter": {"order": "archive"}},  # paging key in filter
        {"action": "offload", "filter": {"limit": "10"}},      # paging key in filter
        {"action": "offload", "filter": {"bogus": "1"}},       # unknown filter param
        {"action": "offload", "filter": "status=failed"},      # non-object filter
        {"action": "offload", "ids": [1], "dry_run": "yes"},   # non-bool dry_run
    )
    for body in bad_bodies:
        try:
            parse_mark_request(body)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{body} must be rejected")


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
