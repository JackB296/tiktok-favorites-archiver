"""Memory Lane: local play history and deterministic resurfacing sections."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import memory, store


def _db():
    return store.init_db(store.connect(":memory:"))


def _item(conn, item_id, date, *, status="done", offloaded=False, missing=False):
    store.insert_item(
        conn,
        item_id,
        f"https://example.test/{item_id}",
        favorited_at=date,
        kind="video",
        status=status,
    )
    conn.execute(
        "UPDATE item SET offloaded = ?, archive_missing = ? WHERE id = ?",
        (int(offloaded), int(missing), item_id),
    )
    conn.commit()


def test_record_play_upserts_count_and_preserves_first_timestamp():
    conn = _db()
    _item(conn, 1, "2022-07-19 10:00:00")

    first = memory.record_play(conn, 1, at="2026-07-18T10:00:00")
    second = memory.record_play(conn, 1, at="2026-07-19T11:00:00")

    assert first == {
        "item_id": 1,
        "play_count": 1,
        "first_played_at": "2026-07-18T10:00:00",
        "last_played_at": "2026-07-18T10:00:00",
    }
    assert second["play_count"] == 2
    assert second["first_played_at"] == "2026-07-18T10:00:00"
    assert second["last_played_at"] == "2026-07-19T11:00:00"


def test_record_play_rejects_unknown_item():
    conn = _db()
    try:
        memory.record_play(conn, 999)
    except memory.MemoryError as error:
        assert "not found" in str(error)
    else:
        raise AssertionError("unknown favorite should fail")


def test_sections_surface_anniversaries_and_least_recently_played_items():
    conn = _db()
    _item(conn, 1, "2022-07-19 10:00:00")
    _item(conn, 2, "2024-07-19 12:00:00")
    _item(conn, 3, "2023-07-02 09:00:00")
    _item(conn, 4, "2025-02-10 09:00:00")
    _item(conn, 5, "2025-03-10 09:00:00")
    memory.record_play(conn, 4, at="2025-04-01T00:00:00")
    memory.record_play(conn, 5, at="2026-07-18T00:00:00")

    result = memory.build_sections(conn, on_date="2026-07-19", limit=3)
    sections = {section["key"]: section for section in result["sections"]}

    assert result["date"] == "2026-07-19"
    assert sections["on_this_day"]["item_ids"] == [2, 1]
    assert sections["forgotten"]["item_ids"] == [3, 4, 5]
    assert sections["era"]["item_ids"] == [3]


def test_sections_only_include_locally_playable_favorites_and_validate_date():
    conn = _db()
    _item(conn, 1, "2024-07-19", status="pending")
    _item(conn, 2, "2024-07-19", offloaded=True)
    _item(conn, 3, "2024-07-19", missing=True)
    _item(conn, 4, "2024-07-19")

    result = memory.build_sections(conn, on_date="2026-07-19")
    assert result["sections"][0]["item_ids"] == [4]

    try:
        memory.build_sections(conn, on_date="July 19")
    except memory.MemoryError as error:
        assert "YYYY-MM-DD" in str(error)
    else:
        raise AssertionError("invalid date should fail")


def test_forgotten_section_includes_playable_favorites_without_a_saved_date():
    conn = _db()
    _item(conn, 1, None)
    _item(conn, 2, "2024-01-01")

    result = memory.build_sections(conn, on_date="2026-07-19")
    forgotten = next(
        section for section in result["sections"] if section["key"] == "forgotten"
    )
    assert forgotten["item_ids"] == [2, 1]


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
