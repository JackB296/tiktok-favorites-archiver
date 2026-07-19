"""Archive Time Machine: immutable import records and adjacent diffs."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import import_history, importer, store


def _write_export(path, favorites):
    with open(path, "w", encoding="utf-8") as target:
        json.dump({"Activity": {"Favorite Videos": {"FavoriteVideoList": [
            {"Link": link, "Date": date} for link, date in favorites
        ]}}}, target)


def test_adjacent_imports_report_new_removed_unchanged_and_protected():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as tmp:
        downloads = os.path.join(tmp, "downloads")
        os.makedirs(downloads)
        first_path = os.path.join(tmp, "first.json")
        second_path = os.path.join(tmp, "second.json")
        _write_export(first_path, [("C", "2023"), ("B", "2022"), ("A", "2021")])
        _write_export(second_path, [("D", "2024"), ("C", "2023"), ("B", "2022")])

        first = importer.import_all(
            conn, first_path, downloads, source_name="../first.json",
        )
        assert first["import_record"]["comparison"]["counts"] == {
            "new": 3, "removed": 0, "unchanged": 0, "protected": 0,
        }
        store.set_status(conn, store.get_item_by_link(conn, "A")["id"], "done")

        second = importer.import_all(
            conn, second_path, downloads, source_name="second.json",
        )
        comparison = second["import_record"]["comparison"]
        assert comparison["counts"] == {
            "new": 1, "removed": 1, "unchanged": 2, "protected": 1,
        }
        assert [entry["link"] for entry in comparison["new"]] == ["D"]
        assert [entry["link"] for entry in comparison["removed"]] == ["A"]
        assert comparison["removed"][0]["protected"] is True
        assert store.get_item_by_link(conn, "A")["status"] == "done"
        assert store.get_item_by_link(conn, "A") is not None

        assert first["import_record"]["source_name"] == "first.json"
        assert second["import_record"]["previous_id"] == first["import_record"]["id"]


def test_repeated_export_is_recorded_with_no_membership_changes():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as tmp:
        downloads = os.path.join(tmp, "downloads")
        os.makedirs(downloads)
        path = os.path.join(tmp, "same.json")
        _write_export(path, [("B", "2022"), ("A", "2021")])
        first = importer.import_all(conn, path, downloads, source_name="same.json")
        second = importer.import_all(conn, path, downloads, source_name="same.json")

    assert first["import_record"]["digest"] == second["import_record"]["digest"]
    assert second["import_record"]["comparison"]["counts"] == {
        "new": 0, "removed": 0, "unchanged": 2, "protected": 0,
    }
    assert len(import_history.list_imports(conn)) == 2
    assert import_history.list_imports(conn)[0]["id"] == second["import_record"]["id"]
    assert import_history.list_imports(conn)[0]["comparison"]["counts"] == {
        "new": 0, "removed": 0, "unchanged": 2, "protected": 0,
    }


def test_import_detail_is_bounded_but_counts_remain_complete():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as tmp:
        downloads = os.path.join(tmp, "downloads")
        os.makedirs(downloads)
        path = os.path.join(tmp, "many.json")
        _write_export(path, [(f"L{i}", f"2024-{i:02d}") for i in range(1, 6)])
        result = importer.import_all(conn, path, downloads, source_name="many.json")

    detail = import_history.get_import(conn, result["import_record"]["id"], change_limit=2)
    assert detail["comparison"]["counts"]["new"] == 5
    assert len(detail["comparison"]["new"]) == 2
    assert detail["comparison"]["truncated"] is True
    assert import_history.get_import(conn, 9999) is None


def test_duplicate_export_links_create_one_membership_without_aborting_checkpoint():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as tmp:
        downloads = os.path.join(tmp, "downloads")
        os.makedirs(downloads)
        path = os.path.join(tmp, "duplicates.json")
        _write_export(path, [
            ("https://www.tiktok.com/@cook/video/1", "2024-01-02"),
            ("https://www.tiktok.com/@cook/video/1", "2024-01-01"),
        ])

        result = importer.import_all(conn, path, downloads)

    record = result["import_record"]
    assert record["comparison"]["counts"] == {
        "new": 1, "removed": 0, "unchanged": 0, "protected": 0,
    }
    assert conn.execute(
        "SELECT COUNT(*) FROM import_membership WHERE import_id = ?",
        (record["id"],),
    ).fetchone()[0] == 1


def test_protected_requires_healthy_local_media_or_a_verified_placement():
    conn = store.init_db(store.connect(":memory:"))
    links = ["missing-local", "legacy-offload", "verified-offload", "healthy-local"]
    for item_id, link in enumerate(links, start=1):
        store.insert_item(conn, item_id, link, status="done")
    conn.execute("UPDATE item SET archive_missing = 1 WHERE id = 1")
    conn.execute("UPDATE item SET offloaded = 1 WHERE id IN (2, 3)")
    conn.commit()
    location_id = store.insert_storage_location(
        conn, "Archive drive", "/mounted/archive", True,
    )
    store.record_media_placement(
        conn, 3, location_id, "items/3", 10, "digest",
        verified=True, files=[],
    )

    first = import_history.record_import(
        conn, [(link, None) for link in links],
    )
    second = import_history.record_import(conn, [])
    detail = import_history.get_import(conn, second["id"])
    protected_by_link = {
        entry["link"]: entry["protected"]
        for entry in detail["comparison"]["removed"]
    }

    assert first["favorite_count"] == 4
    assert protected_by_link == {
        "missing-local": False,
        "legacy-offload": False,
        "verified-offload": True,
        "healthy-local": True,
    }
    assert second["comparison"]["counts"]["protected"] == 2
    assert import_history.list_imports(conn)[0]["comparison"]["counts"]["protected"] == 2


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
