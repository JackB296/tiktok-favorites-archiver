"""Tests for safe migration from the pre-SQLite CLI archive."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import legacy_bootstrap, store


def _make_export(path, favorites, *, current=False):
    """Write oldest-first input as TikTok's newest-first export representation."""
    rows = [{"Link": link, "Date": date} for link, date in reversed(favorites)]
    section = "Likes and Favorites" if current else "Activity"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({section: {"Favorite Videos": {"FavoriteVideoList": rows}}}, f)


def _fixture(root):
    old = [(f"https://tiktok.com/{n}", f"old-{n}") for n in range(1, 9)]
    current = old + [
        ("https://tiktok.com/9", "new-9"),
        ("https://tiktok.com/10", "new-10"),
    ]
    old_path = os.path.join(root, "old.json")
    current_path = os.path.join(root, "current.json")
    checkpoint_path = os.path.join(root, "last_downloaded_link.txt")
    downloads = os.path.join(root, "downloads")
    os.makedirs(downloads)
    _make_export(old_path, old)
    _make_export(current_path, current, current=True)
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        f.write("https://tiktok.com/8\n")
    # max 15 - old checkpoint position 8 = offset 7. The range maps to old
    # positions 5..8; archive #14 is a consumed-but-failed legacy number.
    for item_id in (12, 13, 15):
        open(os.path.join(downloads, f"{item_id}.mp4"), "wb").close()
    return old_path, current_path, checkpoint_path, downloads


def test_preview_builds_exact_legacy_allocation():
    with tempfile.TemporaryDirectory() as d:
        plan = legacy_bootstrap.plan_bootstrap(*_fixture(d))

    preview = plan.preview()
    assert preview["valid"] is True
    assert preview["offset"] == 7
    assert preview["checkpoint"]["old_position"] == 8
    assert preview["checkpoint"]["current_position"] == 8
    assert preview["inventory"] == {
        "local_files": 3,
        "lowest_number": 12,
        "highest_number": 15,
        "mapped_old_position_first": 5,
        "mapped_old_position_last": 8,
        "gaps": 1,
    }
    assert preview["allocation"] == {
        "reserved_physical_first": 1,
        "reserved_physical_last": 11,
        "local_segment_first": 12,
        "local_segment_last": 15,
        "local_done": 3,
        "legacy_gaps_ignored": 1,
        "offloaded_first": 16,
        "offloaded_last": 19,
        "offloaded": 4,
        "new_pending_first": 20,
        "new_pending_last": 21,
        "new_pending": 2,
        "next_archive_number": 22,
        "total_rows": 10,
    }
    assert preview["samples"][0]["archive_number"] == 12
    assert preview["samples"][0]["old_export_position"] == 5
    assert preview["samples"][0]["link"] == "https://tiktok.com/5"
    assert len(preview["token"]) == 64


def test_preview_token_changes_when_numeric_inventory_changes():
    with tempfile.TemporaryDirectory() as d:
        args = _fixture(d)
        first = legacy_bootstrap.plan_bootstrap(*args)
        open(os.path.join(args[3], "14.mp4"), "wb").close()
        second = legacy_bootstrap.plan_bootstrap(*args)
        assert first.token != second.token
        assert second.gap_ids == ()


def test_preview_rejects_checkpoint_that_is_not_old_export_end():
    with tempfile.TemporaryDirectory() as d:
        old_path, current_path, checkpoint_path, downloads = _fixture(d)
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            f.write("https://tiktok.com/7\n")
        try:
            legacy_bootstrap.plan_bootstrap(old_path, current_path, checkpoint_path, downloads)
        except legacy_bootstrap.LegacyBootstrapError as exc:
            assert "final favorite" in str(exc)
        else:
            raise AssertionError("expected a checkpoint validation error")


def test_preview_rejects_current_export_that_is_not_old_export_plus_additions():
    with tempfile.TemporaryDirectory() as d:
        old_path, current_path, checkpoint_path, downloads = _fixture(d)
        changed = [(f"https://tiktok.com/{n}", f"old-{n}") for n in range(1, 9)]
        changed[5] = ("https://tiktok.com/replaced", "changed")
        _make_export(current_path, changed + [("https://tiktok.com/9", "new")], current=True)
        try:
            legacy_bootstrap.plan_bootstrap(old_path, current_path, checkpoint_path, downloads)
        except legacy_bootstrap.LegacyBootstrapError as exc:
            assert "exact prefix" in str(exc)
        else:
            raise AssertionError("expected an export-history validation error")


def test_preview_rejects_duplicate_links_and_empty_inventory():
    with tempfile.TemporaryDirectory() as d:
        old_path, current_path, checkpoint_path, downloads = _fixture(d)
        _make_export(old_path, [
            ("https://tiktok.com/a", "1"),
            ("https://tiktok.com/a", "2"),
        ])
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            f.write("https://tiktok.com/a")
        try:
            legacy_bootstrap.plan_bootstrap(old_path, current_path, checkpoint_path, downloads)
        except legacy_bootstrap.LegacyBootstrapError as exc:
            assert "duplicate" in str(exc)
        else:
            raise AssertionError("expected a duplicate-link validation error")

        for name in os.listdir(downloads):
            os.unlink(os.path.join(downloads, name))
        _make_export(old_path, [("https://tiktok.com/1", "1")])
        _make_export(current_path, [("https://tiktok.com/1", "1")], current=True)
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            f.write("https://tiktok.com/1")
        try:
            legacy_bootstrap.plan_bootstrap(old_path, current_path, checkpoint_path, downloads)
        except legacy_bootstrap.LegacyBootstrapError as exc:
            assert "numeric MP4" in str(exc)
        else:
            raise AssertionError("expected an empty-inventory validation error")


def test_apply_creates_exact_rows_without_touching_media():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as d:
        args = _fixture(d)
        before = sorted(os.listdir(args[3]))
        plan = legacy_bootstrap.plan_bootstrap(*args)
        result = legacy_bootstrap.apply_bootstrap(conn, plan, plan.token)
        after = sorted(os.listdir(args[3]))

    assert before == after
    assert result == {
        "items_created": 10,
        "local_done": 3,
        "legacy_gaps_ignored": 1,
        "offloaded": 4,
        "new_pending": 2,
        "next_archive_number": 22,
    }
    rows = store.all_items(conn)
    assert [row["id"] for row in rows] == [12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
    assert store.get_item(conn, 12)["link"] == "https://tiktok.com/5"
    assert store.get_item(conn, 12)["favorited_at"] == "old-5"
    assert store.get_item(conn, 12)["favorite_order"] == 5
    assert store.get_item(conn, 12)["status"] == "done"
    assert store.get_item(conn, 14)["status"] == "ignored"
    assert "legacy CLI gap" in store.get_item(conn, 14)["error"]
    assert store.get_item(conn, 16)["link"] == "https://tiktok.com/1"
    assert store.get_item(conn, 16)["status"] == "done"
    assert store.get_item(conn, 16)["offloaded"] == 1
    assert store.get_item(conn, 16)["favorite_order"] == 1
    assert store.get_item(conn, 20)["link"] == "https://tiktok.com/9"
    assert store.get_item(conn, 20)["favorited_at"] == "new-9"
    assert store.get_item(conn, 20)["status"] == "pending"
    assert store.get_item(conn, 20)["favorite_order"] == 9
    assert [row["id"] for row in store.page_items(conn, order="latest")] == [21, 20, 15, 14, 13, 12, 19, 18, 17, 16]


def test_apply_refuses_stale_token_and_nonempty_database():
    with tempfile.TemporaryDirectory() as d:
        plan = legacy_bootstrap.plan_bootstrap(*_fixture(d))

    conn = store.init_db(store.connect(":memory:"))
    try:
        legacy_bootstrap.apply_bootstrap(conn, plan, "wrong")
    except legacy_bootstrap.LegacyBootstrapError as exc:
        assert "preview token" in str(exc)
    else:
        raise AssertionError("expected stale-token refusal")
    assert store.all_items(conn) == []

    store.insert_item(conn, 1, "existing")
    try:
        legacy_bootstrap.apply_bootstrap(conn, plan, plan.token)
    except legacy_bootstrap.LegacyBootstrapError as exc:
        assert "empty library" in str(exc)
    else:
        raise AssertionError("expected non-empty-library refusal")
    assert len(store.all_items(conn)) == 1


def test_apply_rolls_back_every_row_when_an_insert_fails():
    conn = store.init_db(store.connect(":memory:"))
    conn.execute("""
        CREATE TRIGGER reject_legacy_row BEFORE INSERT ON item
        WHEN new.id = 17 BEGIN
            SELECT RAISE(ABORT, 'synthetic insert failure');
        END
    """)
    conn.commit()
    with tempfile.TemporaryDirectory() as d:
        plan = legacy_bootstrap.plan_bootstrap(*_fixture(d))
    try:
        legacy_bootstrap.apply_bootstrap(conn, plan, plan.token)
    except Exception as exc:
        assert "synthetic insert failure" in str(exc)
    else:
        raise AssertionError("expected injected database failure")
    assert store.all_items(conn) == []


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
