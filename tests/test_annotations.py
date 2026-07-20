"""Curator Deck annotation persistence, validation, sessions, and filters."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import annotations, memory, store


def _db():
    conn = store.init_db(store.connect(":memory:"))
    for item_id in (1, 2, 3):
        store.insert_item(
            conn, item_id, f"https://tiktok.com/{item_id}",
            kind="video", status="done",
        )
    return conn


def test_annotation_roundtrip_normalizes_tags_and_preserves_review_time():
    conn = _db()
    saved = annotations.save(conn, 1, {
        "starred": True,
        "note": "  Keep this recipe  ",
        "tags": ["Recipe", " recipe ", "Weeknight"],
        "reviewed": True,
    })
    assert saved["starred"] is True
    assert saved["note"] == "Keep this recipe"
    assert saved["tags"] == ["Recipe", "Weeknight"]
    assert saved["reviewed"] is True
    reviewed_at = saved["reviewed_at"]

    updated = annotations.save(conn, 1, {
        "starred": False, "note": "", "tags": ["Food"], "reviewed": True,
    })
    assert updated["reviewed_at"] == reviewed_at
    assert updated["tags"] == ["Food"]


def test_annotation_validation_is_bounded_and_missing_items_fail():
    conn = _db()
    for body in (
        {"starred": "yes"},
        {"note": "x" * 2001},
        {"tags": ["x"] * 21},
        {"tags": [""]},
    ):
        try:
            annotations.save(conn, 1, body)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid annotation: {body}")
    try:
        annotations.save(conn, 99, {})
    except KeyError:
        pass
    else:
        raise AssertionError("missing Favorite was accepted")


def test_sessions_and_gallery_annotation_filters_share_saved_state():
    conn = _db()
    annotations.save(conn, 1, {
        "starred": True, "tags": ["Cooking"], "reviewed": True,
    })
    annotations.save(conn, 2, {"reviewed": False})
    memory.record_play(conn, 2, at="2026-07-19T10:00:00")

    assert [row["id"] for row in annotations.session_rows(
        conn, "unreviewed", 10,
    )] == [3, 2]
    assert [row["id"] for row in annotations.session_rows(
        conn, "forgotten", 10,
    )] == [1, 3, 2]
    assert [row["id"] for row in store.page_items(
        conn, starred=True,
    )] == [1]
    assert [row["id"] for row in store.page_items(
        conn, private_tag_key="cooking",
    )] == [1]


def test_sessions_include_favorites_that_are_not_playback_ready():
    conn = _db()
    conn.execute("UPDATE item SET status = 'expired' WHERE id = 1")
    conn.execute("UPDATE item SET status = 'pending', archive_missing = 1 WHERE id = 2")
    conn.execute("UPDATE item SET status = 'failed', offloaded = 1 WHERE id = 3")

    assert [row["id"] for row in annotations.session_rows(
        conn, "unreviewed", 10,
    )] == [3, 2, 1]


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
