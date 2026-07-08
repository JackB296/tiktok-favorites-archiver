"""Tests for core.manifest — provenance CSV, backfill mapping, numbering (stdlib only)."""
import os
import sys
import csv
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import manifest


def _rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_get_next_starting_count():
    with tempfile.TemporaryDirectory() as d:
        assert manifest.get_next_starting_count(os.path.join(d, "missing")) == 1
        for name in ("1.mp4", "2.mp4", "5.mp4", "notes.txt", "3.mp4.part"):
            open(os.path.join(d, name), "w").close()
        # Only whole-number .mp4 files count; .part and non-mp4 are ignored.
        assert manifest.get_next_starting_count(d) == 6


def test_append_manifest_writes_header_then_rows():
    with tempfile.TemporaryDirectory() as d:
        manifest.append_manifest(d, "1.mp4", "https://tiktok.com/a", "video", "ok")
        manifest.append_manifest(d, "2.mp4", "https://tiktok.com/b", "slideshow", "ok")
        rows = _rows(os.path.join(d, manifest.config.MANIFEST_FILE))
        assert [r["file"] for r in rows] == ["1.mp4", "2.mp4"]
        assert rows[1]["type"] == "slideshow" and rows[1]["status"] == "ok"
        assert rows[0]["timestamp"]


def test_backfill_maps_file_n_to_link_n_and_dedups():
    with tempfile.TemporaryDirectory() as d:
        for n in (1, 2, 3):
            open(os.path.join(d, f"{n}.mp4"), "w").close()
        all_links = ["La", "Lb", "Lc", "Ld"]

        manifest.backfill_manifest(d, all_links)
        mpath = os.path.join(d, manifest.config.MANIFEST_FILE)
        rows = _rows(mpath)
        assert [r["file"] for r in rows] == ["1.mp4", "2.mp4", "3.mp4"]
        assert [r["link"] for r in rows] == ["La", "Lb", "Lc"]  # file N -> link N
        assert all(r["status"] == "backfilled" and r["type"] == "unknown" for r in rows)

        manifest.backfill_manifest(d, all_links)  # idempotent
        assert len(_rows(mpath)) == 3


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
