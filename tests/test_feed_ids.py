"""Tests for core.store.feed_ids — the ordered, unpaged id list that drives a
Feed scoped to a filtered Gallery view (stdlib sqlite3)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store


def _db():
    return store.init_db(store.connect(":memory:"))


def _add(conn, item_id, caption, author, kind="video", favorited_at=None):
    store.insert_item(conn, item_id, f"https://tiktok.com/{item_id}", kind=kind, status="done", favorited_at=favorited_at)
    conn.execute("UPDATE item SET caption = ?, author = ? WHERE id = ?", (caption, author, item_id))
    conn.commit()


def test_no_filter_returns_all_newest_first():
    conn = _db()
    for i in (1, 2, 3):
        _add(conn, i, f"clip {i}", "@a")
    assert store.feed_ids(conn) == [3, 2, 1]  # latest = favorite_order DESC


def test_search_returns_only_matching_ids():
    conn = _db()
    _add(conn, 1, "cincinnati skyline", "@queencity")
    _add(conn, 2, "paris trip", "@wander")
    _add(conn, 3, "cincinnati chili", "@skyline")
    assert set(store.feed_ids(conn, query="cincinnati")) == {1, 3}


def test_prefix_search_matches_like_the_gallery():
    conn = _db()
    _add(conn, 1, "cincinnati skyline", "@a")
    _add(conn, 2, "unrelated", "@b")
    assert set(store.feed_ids(conn, query="cinci")) == {1}  # FTS prefix, same as Gallery search


def test_kind_filter():
    conn = _db()
    _add(conn, 1, "a", "@a", kind="video")
    _add(conn, 2, "b", "@b", kind="slideshow")
    _add(conn, 3, "c", "@c", kind="video")
    assert set(store.feed_ids(conn, kinds=["slideshow"])) == {2}


def test_explicit_sort_order_is_honored():
    conn = _db()
    _add(conn, 1, "a", "@a", favorited_at="2026-03-01")
    _add(conn, 2, "b", "@b", favorited_at="2026-01-01")
    _add(conn, 3, "c", "@c", favorited_at="2026-02-01")
    assert store.feed_ids(conn, order="favorite_date_asc") == [2, 3, 1]
    assert store.feed_ids(conn, order="favorite_date_desc") == [1, 3, 2]


def test_random_requires_seed_and_returns_full_set():
    conn = _db()
    for i in (1, 2, 3):
        _add(conn, i, f"clip {i}", "@a")
    try:
        store.feed_ids(conn, order="random")
        assert False, "expected ValueError without a seed"
    except ValueError:
        pass
    assert set(store.feed_ids(conn, order="random", seed=7)) == {1, 2, 3}


def test_unknown_filter_raises():
    conn = _db()
    try:
        store.feed_ids(conn, bogus=1)
        assert False, "expected ValueError for unknown filter"
    except ValueError:
        pass


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
