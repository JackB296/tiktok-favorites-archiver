"""Public comment-search behavior over locally saved snapshot history."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import comment_search, store


def _db():
    return store.init_db(store.connect(":memory:"))


def test_latest_search_is_default_and_history_can_find_removed_comments():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/@potter/video/1", status="done")
    store.set_metadata(conn, 1, "A pottery lesson", "potter")
    store.record_comment_snapshot(conn, 1, [
        {"id": "old", "author_username": "firstviewer", "text": "moonstone glaze"},
    ], captured_at="2026-08-01T10:00:00")
    store.record_comment_snapshot(conn, 1, [
        {"id": "new", "author_username": "localcritic", "text": "celadon glaze"},
    ], captured_at="2026-08-02T10:00:00")

    assert comment_search.search(conn, "moonstone")["results"] == []
    latest = comment_search.search(conn, "celadon")["results"]
    assert [(row["item_id"], row["author_username"], row["latest"]) for row in latest] == [
        (1, "localcritic", True),
    ]
    historical = comment_search.search(conn, "moonstone", include_history=True)["results"]
    assert [(row["text"], row["captured_at"], row["latest"]) for row in historical] == [
        ("moonstone glaze", "2026-08-01T10:00:00", False),
    ]


def test_comment_search_supports_author_post_and_engagement_field_syntax():
    conn = _db()
    for item_id in (1, 2):
        store.insert_item(conn, item_id, f"https://tiktok.com/video/{item_id}", status="done")
    conn.execute("UPDATE item SET source_posted_at = '2025-03-04', view_count = 50000 WHERE id = 1")
    conn.execute("UPDATE item SET source_posted_at = '2023-03-04', view_count = 50 WHERE id = 2")
    store.record_comment_snapshot(conn, 1, [{
        "id": "one", "author_username": "alice", "text": "beautiful framing", "like_count": 12,
    }])
    store.record_comment_snapshot(conn, 2, [{
        "id": "two", "author_username": "bob", "text": "beautiful colors", "like_count": 1,
    }])

    result = comment_search.search(
        conn, '"beautiful framing" author:alice views:>1000 posted:2025 likes:>10',
    )
    assert [row["item_id"] for row in result["results"]] == [1]


if __name__ == "__main__":
    import traceback
    failures = 0
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"PASS {name}")
            except Exception:
                failures += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    raise SystemExit(1 if failures else 0)
