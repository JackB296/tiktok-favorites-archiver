"""Tests for core.export — export parsing (stdlib only).

Runnable two ways: `python3 -m pytest tests/test_export.py` or, when pytest
isn't installed, `python3 tests/test_export.py` (self-contained runner below).
"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import export


def _make_export(path, links):
    data = {"Activity": {"Favorite Videos": {"FavoriteVideoList": [{"Link": l} for l in links]}}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_load_all_links_reverses_and_substitutes():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "e.json")
        _make_export(p, ["https://www.tiktokv.com/a", "https://www.tiktokv.com/b"])
        assert export.load_all_links(p) == ["https://www.tiktok.com/b", "https://www.tiktok.com/a"]


def test_load_all_links_missing_file_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        assert export.load_all_links(os.path.join(d, "nope.json")) == []


def test_load_all_links_skips_items_without_link():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "e.json")
        data = {"Activity": {"Favorite Videos": {"FavoriteVideoList": [
            {"Link": "https://tiktok.com/x"}, {"Date": "2020-01-01"}]}}}
        with open(p, "w") as f:
            json.dump(data, f)
        assert export.load_all_links(p) == ["https://tiktok.com/x"]


def test_load_all_favorites_accepts_current_likes_and_favorites_schema():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "current.json")
        data = {"Likes and Favorites": {"Favorite Videos": {"FavoriteVideoList": [
            {"Link": "https://www.tiktokv.com/new", "Date": "2026-07-11"},
            {"Link": "https://www.tiktok.com/old", "Date": "2026-07-10"},
        ]}}}
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f)

        assert export.load_all_favorites(p) == [
            ("https://www.tiktok.com/old", "2026-07-10"),
            ("https://www.tiktok.com/new", "2026-07-11"),
        ]



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
