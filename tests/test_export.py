"""Tests for core.export — export parsing + resume bookmark (stdlib only).

Runnable two ways: `python3 -m pytest tests/test_export.py` or, when pytest
isn't installed, `python3 tests/test_export.py` (self-contained runner below).
"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config, export


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


def test_read_video_links_resume():
    old = config.LAST_DOWNLOADED_LINK_FILE
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "e.json")
        bm = os.path.join(d, "last.txt")
        _make_export(p, ["L5", "L4", "L3", "L2", "L1"])  # reversed -> L1..L5
        config.LAST_DOWNLOADED_LINK_FILE = bm
        try:
            # A fresh read must NOT write the bookmark (the resume-bug regression).
            assert export.read_video_links(p) == ["L1", "L2", "L3", "L4", "L5"]
            assert not os.path.exists(bm)
            # After finishing L2, resume continues from L3.
            export.write_last_downloaded_link(bm, "L2")
            assert export.read_video_links(p) == ["L3", "L4", "L5"]
        finally:
            config.LAST_DOWNLOADED_LINK_FILE = old


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
