"""Tests for the Archive-item projection module (stdlib only)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store
from server.archive_items import ArchiveItems, gallery_preset_filters, parse_mark_request, parse_page_query


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
    query = parse_page_query({"assets": "without", "recovery": "false", "kind": ""})

    assert query == {"has_assets": False, "recovery": False, "kinds": None}


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


def test_gallery_presets_accept_the_offloaded_filter():
    assert gallery_preset_filters({"offloaded": "with", "search": "games"}) == {
        "offloaded": "with",
        "search": "games",
    }


def test_public_projection_includes_the_offloaded_flag():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/a", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/b", status="done")
    store.set_offloaded(conn, [1])

    with tempfile.TemporaryDirectory() as dl:
        items = ArchiveItems(conn, dl)
        assert items.get(1)["offloaded"] is True
        assert items.get(2)["offloaded"] is False


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
