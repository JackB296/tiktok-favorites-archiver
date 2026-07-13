"""Tests for core.store.suggest — archive-grounded search typeahead (stdlib sqlite3)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store


def _db():
    return store.init_db(store.connect(":memory:"))


def _add(conn, item_id, author, caption):
    store.insert_item(conn, item_id, f"https://tiktok.com/{item_id}", status="done")
    conn.execute("UPDATE item SET author = ?, caption = ? WHERE id = ?", (author, caption, item_id))
    conn.commit()


def test_empty_query_returns_empty_groups():
    conn = _db()
    _add(conn, 1, "@catlover", "#cats storytime")
    empty = {"creators": [], "hashtags": [], "terms": []}
    assert store.suggest(conn, "") == empty
    assert store.suggest(conn, "   ") == empty


def test_suggests_only_creators_and_hashtags_that_exist():
    conn = _db()
    _add(conn, 1, "@catlover", "#cats cute kitten")
    _add(conn, 2, "@catlover", "#catsoftiktok nap time")
    _add(conn, 3, "@chefmike", "#cooking pasta night")
    out = store.suggest(conn, "cat")
    creators = [c["value"] for c in out["creators"]]
    hashtags = [h["value"] for h in out["hashtags"]]
    assert creators == ["@catlover"]  # the real creator, deduped to one entry
    assert "#cats" in hashtags and "#catsoftiktok" in hashtags
    assert "@chefmike" not in creators  # an unrelated creator is never offered


def test_ranks_by_frequency():
    conn = _db()
    for i in range(1, 4):
        _add(conn, i, "@a", "#gaming clip")  # #gaming appears in 3 favorites
    _add(conn, 9, "@b", "#garden tour")  # #garden in 1
    hashtags = [h["value"] for h in store.suggest(conn, "ga")["hashtags"]]
    assert hashtags[0] == "#gaming"
    assert set(hashtags) == {"#gaming", "#garden"}


def test_counts_reflect_favorite_frequency():
    conn = _db()
    for i in range(1, 3):
        _add(conn, i, "@catlover", "#cats")
    out = store.suggest(conn, "catlover")
    assert out["creators"][0] == {"value": "@catlover", "count": 2}


def test_no_match_returns_empty():
    conn = _db()
    _add(conn, 1, "@catlover", "#cats")
    assert store.suggest(conn, "zzz") == {"creators": [], "hashtags": [], "terms": []}


def test_keyword_terms_exclude_hashtag_duplicates():
    conn = _db()
    _add(conn, 1, "@a", "cooking #cooking the recipe")
    out = store.suggest(conn, "cook")
    assert "#cooking" in [h["value"] for h in out["hashtags"]]
    assert "cooking" not in [t["value"] for t in out["terms"]]  # not duplicated as a bare word


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
