"""Local sparse-embedding search and related-Favorite ranking."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store, vibes


def _db():
    conn = store.init_db(store.connect(":memory:"))
    rows = (
        (1, "late night ramen cooking in a tiny kitchen", "chef"),
        (2, "easy weeknight pasta recipe and kitchen tips", "cook"),
        (3, "morning trail run through the mountains", "runner"),
    )
    for item_id, caption, author in rows:
        store.insert_item(
            conn, item_id, f"https://tiktok.com/{item_id}",
            kind="video", status="done",
        )
        store.set_metadata(conn, item_id, caption, author)
    return conn


def test_prompt_search_ranks_matching_archive_meaning_and_explains_it():
    results = vibes.search(_db(), "late night ramen cooking", 3)
    assert results[0]["item_id"] == 1
    assert "night" in results[0]["evidence"]
    assert results[0]["score"] > results[-1]["score"]


def test_related_excludes_seed_and_prefers_shared_concepts():
    results = vibes.related(_db(), 1, 3)
    assert all(result["item_id"] != 1 for result in results)
    assert results[0]["item_id"] == 2


def test_query_and_limit_validation_is_bounded():
    conn = _db()
    for query, limit in (("", 10), ("x" * 241, 10), ("food", 0), ("food", 51)):
        try:
            vibes.search(conn, query, limit)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid search was accepted")


def test_search_keeps_unicode_archive_terms():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(
        conn, 1, "https://tiktok.com/unicode", kind="video", status="done",
    )
    store.set_metadata(conn, 1, "深夜 ラーメン café", "料理")
    assert vibes.search(conn, "深夜 ラーメン", 3)[0]["item_id"] == 1


def test_stemmed_matches_include_a_human_readable_evidence_term():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(
        conn, 1, "https://tiktok.com/recipe", kind="video", status="done",
    )
    store.set_metadata(conn, 1, "one recipe", "chef")

    result = vibes.search(conn, "recipes", 3)[0]

    assert result["item_id"] == 1
    assert result["evidence"] == ["recipe"]


def test_ranking_reuses_the_precomputed_document_terms():
    docs = vibes.documents(_db())
    original_words = vibes._words
    calls = 0

    def count_words(text):
        nonlocal calls
        calls += 1
        return original_words(text)

    vibes._words = count_words
    try:
        vibes._rank(docs, "late night", 3)
    finally:
        vibes._words = original_words

    assert calls == 1  # The query only; documents were prepared once above.


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
