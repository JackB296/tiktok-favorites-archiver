"""Tests for the portable archive inventory CSV."""
import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import inventory, store


def test_inventory_csv_has_stable_columns_and_escapes_text():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://tiktok.com/a", favorited_at="2025-01-01", kind="video", status="done")
    store.set_metadata(conn, 1, 'A caption, with "quotes"', "creator")
    data = "".join(inventory.csv_lines(store.all_items(conn)))
    rows = list(csv.DictReader(io.StringIO(data)))

    assert rows == [{
        "id": "1", "favorited_at": "2025-01-01", "status": "done", "kind": "video",
        "attempt_count": "0", "last_attempt_at": "", "archive_missing": "0",
        "caption": 'A caption, with "quotes"', "author": "creator", "duration_s": "",
        "media_width": "", "media_height": "", "media_codec": "", "media_size": "",
        "link": "https://tiktok.com/a",
    }]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
