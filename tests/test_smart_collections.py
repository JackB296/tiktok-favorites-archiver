"""Existing Gallery presets resolve as live Smart collections."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core import selection, store
from server import archive_items


def database():
    conn = store.connect(":memory:")
    store.init_db(conn)
    for item_id, caption, status in (
        (1, "cats first", "done"),
        (2, "dogs", "done"),
        (3, "cats newest", "done"),
    ):
        store.insert_item(conn, item_id, f"https://tiktok.com/video/{item_id}", "video", status)
        store.set_metadata(conn, item_id, caption, "creator")
    return conn


def test_presets_resolve_live_membership_and_gallery_order():
    conn = database()
    preset_id = store.save_saved_list(
        conn, "gallery_preset", "Cats",
        {"filters": {"search": "cats", "order": "archive"}},
    )
    preset, feed = selection.ArchiveSelection.smart_collection(
        conn, preset_id, scope="feed",
        query_from_filters=archive_items.gallery_preset_query,
    )
    assert preset["name"] == "Cats"
    assert feed.ids(conn) == [1, 3]

    store.set_metadata(conn, 2, "cats and dogs", "creator")
    _preset, live = selection.ArchiveSelection.smart_collection(
        conn, preset_id, scope="feed",
        query_from_filters=archive_items.gallery_preset_query,
    )
    assert live.ids(conn) == [1, 2, 3]


def test_set_scope_has_same_membership_and_playback_queues_stay_fixed():
    conn = database()
    preset_id = store.save_saved_list(
        conn, "gallery_preset", "Cats",
        {"filters": {"search": "cats", "order": "latest"}},
    )
    queue_id = store.save_saved_list(
        conn, "playback_queue", "Fixed", {"item_ids": [3, 1]},
    )
    _preset, smart_set = selection.ArchiveSelection.smart_collection(
        conn, preset_id, scope="set",
        query_from_filters=archive_items.gallery_preset_query,
    )
    assert set(smart_set.ids(conn)) == {1, 3}
    store.set_metadata(conn, 2, "now cats", "creator")
    assert store.get_saved_list(conn, "playback_queue", queue_id)["item_ids"] == [3, 1]


def test_preset_unit_and_date_conversion_matches_gallery_wire_contract():
    query = archive_items.gallery_preset_query({
        "minSize": "0.1", "maxDuration": "12.5",
        "dateTo": "2026-07-17", "recovery": True,
    })
    assert query["min_size"] == 104858
    assert query["max_duration"] == 12.5
    assert query["date_to"] == "2026-07-17T23:59:59"
    assert query["recovery"] is True


if __name__ == "__main__":
    for name, fn in sorted(globals().copy().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
