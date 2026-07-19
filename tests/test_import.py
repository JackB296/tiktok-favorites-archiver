"""Tests for core.importer — export+files -> DB, manifest regeneration (stdlib)."""
import os
import sys
import csv
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store, importer


def _make_export(path, favorites):
    """favorites = list of (link, date) in newest-first order (as TikTok exports)."""
    data = {"Activity": {"Favorite Videos": {"FavoriteVideoList": [
        {"Link": link, "Date": date} for link, date in favorites]}}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_import_export_orders_and_dates():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as d:
        exp = os.path.join(d, "e.json")
        # export is newest-first; importer reverses -> La(id1) .. Lc(id3)
        _make_export(exp, [("Lc", "2023"), ("Lb", "2022"), ("La", "2021")])
        n = importer.import_export(conn, exp)
        assert n == 3
        assert [r["link"] for r in store.all_items(conn)] == ["La", "Lb", "Lc"]
        assert store.get_item(conn, 1)["favorited_at"] == "2021"
        assert store.get_item(conn, 3)["link"] == "Lc"


def test_import_ignores_crashed_encode_temp_files():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "1.mp4"), "w").close()          # finished item
        open(os.path.join(dl, "2.mp4.part.mp4"), "w").close()  # crashed slideshow encode
        open(os.path.join(dl, "3.mp4.part"), "w").close()      # crashed video download
        marked = importer.import_existing_files(conn, dl)
    assert marked == 1
    assert store.get_item(conn, 1)["status"] == "done"
    assert store.get_item(conn, 2) is None
    assert store.get_item(conn, 3) is None


def test_import_existing_files_and_assets_and_manifest():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as d:
        exp = os.path.join(d, "e.json")
        dl = os.path.join(d, "downloads")
        os.makedirs(dl)
        _make_export(exp, [("Lc", "2023"), ("Lb", "2022"), ("La", "2021")])  # -> La,Lb,Lc
        # Files 1.mp4 and 2.mp4 already downloaded; 2 is a slideshow with raw assets.
        open(os.path.join(dl, "1.mp4"), "w").close()
        open(os.path.join(dl, "2.mp4"), "w").close()
        os.makedirs(os.path.join(dl, "2"))

        result = importer.import_all(conn, exp, dl)
        assert {
            key: result[key] for key in ("favorites", "existing_files", "manifest_rows")
        } == {"favorites": 3, "existing_files": 2, "manifest_rows": 2}
        assert result["import_record"]["favorite_count"] == 3
        assert result["import_record"]["comparison"]["counts"]["new"] == 3

        assert store.get_item(conn, 1)["status"] == "done"
        assert store.get_item(conn, 2)["status"] == "done"
        assert store.get_item(conn, 2)["has_assets"] == 1
        assert store.get_item(conn, 3)["status"] == "pending"  # not downloaded yet

        rows = _rows(os.path.join(dl, importer.config.MANIFEST_FILE))
        assert [r["file"] for r in rows] == ["1.mp4", "2.mp4"]
        assert [r["link"] for r in rows] == ["La", "Lb"]


def test_import_is_idempotent():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as d:
        exp = os.path.join(d, "e.json")
        dl = os.path.join(d, "downloads")
        os.makedirs(dl)
        _make_export(exp, [("Lb", "2022"), ("La", "2021")])
        open(os.path.join(dl, "1.mp4"), "w").close()

        importer.import_all(conn, exp, dl)
        importer.import_all(conn, exp, dl)  # second run must not duplicate
        assert len(store.all_items(conn)) == 2
        assert _rows(os.path.join(dl, importer.config.MANIFEST_FILE))  # still valid
        assert len(_rows(os.path.join(dl, importer.config.MANIFEST_FILE))) == 1


def test_missing_export_does_not_create_an_empty_history_checkpoint():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as d:
        exp = os.path.join(d, "e.json")
        _make_export(exp, [("La", "2021")])
        first = importer.import_all(conn, exp, d)

        missing = importer.import_all(
            conn, os.path.join(d, "missing.json"), d,
        )

    assert first["import_record"] is not None
    assert missing["favorites"] == 0
    assert missing["import_record"] is None
    assert conn.execute("SELECT COUNT(*) FROM import_history").fetchone()[0] == 1


def test_orphan_file_beyond_export_is_represented():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as d:
        exp = os.path.join(d, "e.json")
        dl = os.path.join(d, "downloads")
        os.makedirs(dl)
        _make_export(exp, [("La", "2021")])         # only 1 favorite
        open(os.path.join(dl, "1.mp4"), "w").close()
        open(os.path.join(dl, "7.mp4"), "w").close()  # orphan (no matching favorite)

        importer.import_all(conn, exp, dl)
        orphan = store.get_item(conn, 7)
        assert orphan is not None and orphan["status"] == "done"
        assert orphan["link"].startswith("local://")


def test_manifest_neutralizes_formula_prefixed_links():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as dl:
        store.insert_item(conn, 1, '=HYPERLINK("http://evil")', favorite_order=1)
        open(os.path.join(dl, "1.mp4"), "w").close()
        importer.regenerate_manifest(conn, dl)
        with open(os.path.join(dl, importer.config.MANIFEST_FILE), newline="") as f:
            rows = list(csv.reader(f))
    assert rows[1][1] == '\'=HYPERLINK("http://evil")'


def test_orphan_file_uses_next_logical_order_when_physical_id_would_collide():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 100, "known", favorite_order=7)
    with tempfile.TemporaryDirectory() as dl:
        open(os.path.join(dl, "7.mp4"), "w").close()
        importer.import_existing_files(conn, dl)

    assert store.get_item(conn, 7)["favorite_order"] == 8


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
