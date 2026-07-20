"""Smart Collection-backed Archive Channel CRUD and ordering."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import channels, memory, store
from server.archive_items import gallery_preset_query


def _db():
    conn = store.init_db(store.connect(":memory:"))
    for item_id in (1, 2, 3, 4):
        store.insert_item(
            conn, item_id, f"https://tiktok.com/{item_id}",
            kind="video", status="done",
        )
    preset_id = store.save_saved_list(
        conn, "gallery_preset", "Ready", {"filters": {"status": "done"}},
    )
    return conn, preset_id


def test_channel_crud_and_live_collection_resolution():
    conn, preset_id = _db()
    channel = channels.create(conn, {
        "name": "Dinner TV", "preset_id": preset_id,
        "shuffle": False, "prefer_unwatched": False,
    })
    assert channels.list_channels(conn) == [channel]
    resolved, ids = channels.item_ids(conn, channel["id"], gallery_preset_query)
    assert resolved["preset_name"] == "Ready"
    assert ids == [4, 3, 2, 1]

    store.insert_item(
        conn, 5, "https://tiktok.com/5", kind="video", status="done",
    )
    assert channels.item_ids(
        conn, channel["id"], gallery_preset_query,
    )[1][0] == 5
    assert channels.delete(conn, channel["id"]) is True
    assert channels.list_channels(conn) == []


def test_prefer_unwatched_is_a_stable_partition_and_shuffle_is_repeatable():
    conn, preset_id = _db()
    memory.record_play(conn, 4, at="2026-07-20T10:00:00")
    preferred = channels.create(conn, {
        "name": "Fresh first", "preset_id": preset_id,
        "prefer_unwatched": True,
    })
    assert channels.item_ids(
        conn, preferred["id"], gallery_preset_query,
    )[1] == [3, 2, 1, 4]

    shuffled = channels.create(conn, {
        "name": "Shuffle", "preset_id": preset_id,
        "shuffle": True, "prefer_unwatched": False,
    })
    first = channels.item_ids(conn, shuffled["id"], gallery_preset_query)[1]
    second = channels.item_ids(conn, shuffled["id"], gallery_preset_query)[1]
    assert first == second
    assert sorted(first) == [1, 2, 3, 4]


def test_channels_exclude_noncontinuous_archive_markers():
    conn, preset_id = _db()
    conn.execute("UPDATE item SET offloaded = 1 WHERE id = 1")
    conn.execute("UPDATE item SET archive_missing = 1 WHERE id = 2")
    conn.execute("UPDATE item SET status = 'expired' WHERE id = 3")
    conn.commit()
    channel = channels.create(conn, {
        "name": "Playable only", "preset_id": preset_id,
        "prefer_unwatched": False,
    })
    assert channels.item_ids(
        conn, channel["id"], gallery_preset_query,
    )[1] == [4]


def test_channel_validation_rejects_missing_presets_and_bad_flags():
    conn, _preset_id = _db()
    for body in (
        {"name": "", "preset_id": 1},
        {"name": "No preset", "preset_id": 999},
        {"name": "Bad flag", "preset_id": 1, "shuffle": "yes"},
    ):
        try:
            channels.create(conn, body)
        except (ValueError, KeyError):
            pass
        else:
            raise AssertionError(f"accepted invalid channel: {body}")


if __name__ == "__main__":
    import traceback
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception:
            failures += 1
            print(f"FAIL {test.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failures else 0)
