"""One normalized Archive selection across page, Feed, sets, and bulk."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import curation, selection, store


def _db():
    conn = store.init_db(store.connect(":memory:"))
    for item_id, author, caption, status in (
        (1, "alice", "#cats first", "done"),
        (2, "bob", "#dogs second", "failed"),
        (3, "alice", "#cats newest", "done"),
    ):
        store.insert_item(conn, item_id, f"https://tiktok.com/{item_id}", status=status)
        store.set_metadata(conn, item_id, caption, author)
    return conn


def test_page_feed_and_set_share_filters_but_keep_their_scope_ordering():
    conn = _db()
    query = {"query": "cats", "kinds": ["unknown"], "order": "latest"}

    page = selection.ArchiveSelection.gallery(query, scope="page")
    feed = selection.ArchiveSelection.gallery(query, scope="feed")
    item_set = selection.ArchiveSelection.gallery(
        {"query": "cats", "kinds": ["unknown"]}, scope="set",
    )

    assert [row["id"] for row in page.rows(conn)] == [3, 1]
    assert feed.ids(conn) == [3, 1]
    assert item_set.ids(conn) == [1, 3]


def test_bulk_selector_uses_the_same_normalized_filter():
    conn = _db()
    selected = selection.ArchiveSelection.bulk(
        "filter", {"statuses": ["failed"]},
    )

    assert selected.ids(conn) == [2]
    assert curation.resolve_selector(conn, "filter", {"statuses": ["failed"]}) == [2]


def test_explicit_and_range_bulk_selections_are_normalized_and_deduplicated():
    conn = _db()

    assert selection.ArchiveSelection.bulk("ids", [3, 1, 3]).ids(conn) == [3, 1]
    assert selection.ArchiveSelection.bulk(
        "range", {"first_id": 2, "last_id": 9},
    ).ids(conn) == [2, 3]


def test_set_scopes_reject_every_paging_or_ordering_field():
    for field, value in (
        ("limit", 10),
        ("cursor", 2),
        ("order", "archive"),
        ("seed", 9),
        ("feed", True),
    ):
        try:
            selection.ArchiveSelection.gallery({field: value}, scope="set")
        except ValueError as exc:
            assert f"{field} is not a filter" in str(exc)
        else:
            raise AssertionError(f"set selection accepted {field}")


def test_invalid_fields_and_modes_fail_during_normalization():
    for call in (
        lambda: selection.ArchiveSelection.gallery({"nope": 1}, scope="page"),
        lambda: selection.ArchiveSelection.gallery({}, scope="mystery"),
        lambda: selection.ArchiveSelection.bulk("mystery", {}),
    ):
        try:
            call()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid selection was accepted")


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
