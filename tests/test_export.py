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


def test_load_all_favorites_reverses_and_substitutes():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "e.json")
        _make_export(p, ["https://www.tiktokv.com/a", "https://www.tiktokv.com/b"])
        assert [link for link, _date in export.load_all_favorites(p)] == [
            "https://www.tiktok.com/b", "https://www.tiktok.com/a",
        ]


def test_load_all_favorites_missing_file_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        assert export.load_all_favorites(os.path.join(d, "nope.json")) == []


def test_load_all_favorites_skips_items_without_link():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "e.json")
        data = {"Activity": {"Favorite Videos": {"FavoriteVideoList": [
            {"Link": "https://tiktok.com/x"}, {"Date": "2020-01-01"}]}}}
        with open(p, "w") as f:
            json.dump(data, f)
        assert [link for link, _date in export.load_all_favorites(p)] == ["https://tiktok.com/x"]


def test_normalization_rewrites_only_literal_tiktokv_domain():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "e.json")
        _make_export(p, ["https://www.tiktokv.com/a", "https://www.tiktokvXcom/b"])
        assert [link for link, _date in export.load_all_favorites(p)] == [
            "https://www.tiktokvXcom/b",
            "https://www.tiktok.com/a",
        ]


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



def _raises_export_error(path):
    try:
        export.load_all_favorites(path)
    except export.ExportError:
        return True
    return False


def test_unusable_content_raises_the_typed_export_error():
    with tempfile.TemporaryDirectory() as d:
        malformed = os.path.join(d, "bad.json")
        with open(malformed, "w") as f:
            f.write("{not json")
        assert _raises_export_error(malformed)          # invalid JSON -> error, not []

        array = os.path.join(d, "array.json")
        with open(array, "w") as f:
            json.dump([1, 2], f)
        assert _raises_export_error(array)              # not an object

        wrong_shape = os.path.join(d, "shape.json")
        with open(wrong_shape, "w") as f:
            json.dump({"Activity": "text"}, f)
        assert _raises_export_error(wrong_shape)        # section is not a dict (used to 500)

        bad_link = os.path.join(d, "link.json")
        with open(bad_link, "w") as f:
            json.dump({"Activity": {"Favorite Videos": {"FavoriteVideoList": [{"Link": 5}]}}}, f)
        assert _raises_export_error(bad_link)           # non-string link


def test_present_but_malformed_favorites_list_gets_an_accurate_error():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "null.json")
        with open(p, "w") as f:
            json.dump({"Activity": {"Favorite Videos": {"FavoriteVideoList": None}}}, f)
        try:
            export.load_all_favorites(p)
        except export.ExportError as error:
            assert "malformed" in str(error)  # not "no favorites section found"
        else:
            raise AssertionError("expected ExportError")


def test_missing_file_stays_a_soft_empty_result_for_the_cli():
    with tempfile.TemporaryDirectory() as d:
        assert export.load_all_favorites(os.path.join(d, "nope.json")) == []


def test_present_but_empty_favorites_list_is_a_valid_empty_export():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "empty.json")
        _make_export(p, [])
        assert export.load_all_favorites(p) == []


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
