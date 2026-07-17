"""Creator/Hashtag identity normalization, exact filters, trends, and resume."""
from datetime import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core import discovery, migrations, store


def db():
    return store.init_db(store.connect(":memory:"))


def test_unicode_normalization_and_unique_relationships():
    assert discovery.normalize_creator(" @Ｆｏｏ ") == "foo"
    assert discovery.normalize_hashtag(" #CAFÉ ") == "café"
    assert discovery.extract_hashtags("Hi #Cats #ＣＡＴＳ #café #café!") == [
        ("cats", "#Cats"), ("café", "#café"),
    ]
    conn = db()
    store.insert_item(conn, 1, "https://example/1")
    store.set_metadata(conn, 1, "#Cats #cats #café", "@Ｆｏｏ")
    identities = discovery.identities_for_items(conn, [1])[1]
    assert identities["creator"]["key"] == "foo"
    assert [tag["key"] for tag in identities["hashtags"]] == ["cats", "café"]


def test_exact_filters_do_not_use_substrings():
    conn = db()
    for item_id, author, caption in (
        (1, "@ann", "#cat"),
        (2, "@anna", "#cats"),
    ):
        store.insert_item(conn, item_id, f"https://example/{item_id}")
        store.set_metadata(conn, item_id, caption, author)
    assert store.feed_ids(conn, creator_key="ann") == [1]
    assert store.feed_ids(conn, hashtag_key="cat") == [1]
    assert [row["id"] for row in store.page_items(
        conn, query="cat", hashtag_key="cat",
    )] == [1]


def test_resource_counts_search_and_trends():
    conn = db()
    for item_id, when in ((1, "2026-01-01"), (2, "2026-02-01")):
        store.insert_item(conn, item_id, f"https://example/{item_id}", favorited_at=when)
        store.set_metadata(conn, item_id, "#Cats", "@Creator")
    creators = discovery.list_entities(conn, "creator", search="@cre")
    assert creators["items"][0]["count"] == 2
    detail = discovery.get_entity(conn, "hashtag", 1)
    assert detail["count"] == 2
    assert detail["trend"] == [
        {"month": "2026-01", "count": 1},
        {"month": "2026-02", "count": 1},
    ]


def test_backfill_resumes_from_persisted_cursor():
    conn = db()
    for item_id in range(1, 4):
        store.insert_item(conn, item_id, f"https://example/{item_id}")
        conn.execute(
            "UPDATE item SET author = ?, caption = ? WHERE id = ?",
            ("@Old", f"#tag{item_id}", item_id),
        )
    conn.commit()
    conn.execute("DELETE FROM creator")
    conn.execute("DELETE FROM hashtag")
    conn.execute("DELETE FROM item_hashtag")
    conn.execute("UPDATE item SET creator_id = NULL")
    conn.execute(
        "UPDATE backfill_state SET status='running', cursor='1', processed=1 "
        "WHERE name = ?", (discovery.BACKFILL,),
    )
    conn.commit()
    discovery.run_backfill(conn, "", batch_size=1)
    state = migrations.get_backfill(conn, discovery.BACKFILL)
    assert state["status"] == "completed"
    assert state["processed"] == 3
    assert discovery.identities_for_items(conn, [1, 2, 3])[1]["creator"] is None
    assert discovery.identities_for_items(conn, [1, 2, 3])[2]["creator"]["key"] == "old"


if __name__ == "__main__":
    for name, fn in sorted(globals().copy().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
