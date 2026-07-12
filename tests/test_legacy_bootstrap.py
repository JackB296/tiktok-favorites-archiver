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


def _piecewise_fixture(root):
    old = [(f"https://tiktok.com/{n}", f"old-{n}") for n in range(1, 11)]
    current = old + [
        ("https://tiktok.com/11", "new-11"),
        ("https://tiktok.com/12", "new-12"),
    ]
    old_path = os.path.join(root, "old.json")
    current_path = os.path.join(root, "current.json")
    checkpoint_path = os.path.join(root, "last_downloaded_link.txt")
    downloads = os.path.join(root, "downloads")
    os.makedirs(downloads)
    _make_export(old_path, old)
    _make_export(current_path, current, current=True)
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        f.write("https://tiktok.com/10\n")
    # First run: #12..#14 -> positions 5..7 (offset 7), with #13 missing.
    # Position 8 then failed at the end of that run. The restart reused #15,
    # so #15..#16 -> positions 9..10 (offset 6).
    for item_id in (12, 14, 15, 16):
        open(os.path.join(downloads, f"{item_id}.mp4"), "wb").close()
    segments = [
        {"start_id": 12, "offset": 7},
        {"start_id": 15, "offset": 6},
    ]
    return (old_path, current_path, checkpoint_path, downloads), segments


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
        "physical_gaps": 1,
        "reused_number_markers": 0,
        "gaps": 1,
    }
    assert preview["allocation"] == {
        "reserved_physical_first": 1,
        "reserved_physical_last": 11,
        "local_segment_first": 12,
        "local_segment_last": 15,
        "local_done": 3,
        "legacy_gaps_ignored": 1,
        "physical_gaps_ignored": 1,
        "reused_number_markers": 0,
        "offloaded_first": 16,
        "offloaded_last": 19,
        "offloaded": 4,
        "reused_marker_first": None,
        "reused_marker_last": None,
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


def test_piecewise_preview_preserves_reused_number_position():
    with tempfile.TemporaryDirectory() as d:
        args, segments = _piecewise_fixture(d)
        plan = legacy_bootstrap.plan_bootstrap(*args, mapping_segments=segments)

    preview = plan.preview()
    assert preview["segments"] == [
        {
            "start_id": 12,
            "end_id": 14,
            "offset": 7,
            "first_position": 5,
            "last_position": 7,
        },
        {
            "start_id": 15,
            "end_id": 16,
            "offset": 6,
            "first_position": 9,
            "last_position": 10,
        },
    ]
    assert plan.reused_number_positions == (8,)
    assert preview["inventory"]["mapped_old_position_first"] == 5
    assert preview["inventory"]["mapped_old_position_last"] == 10
    assert preview["inventory"]["physical_gaps"] == 1
    assert preview["inventory"]["reused_number_markers"] == 1
    assert preview["inventory"]["gaps"] == 2
    assert preview["allocation"] == {
        "reserved_physical_first": 1,
        "reserved_physical_last": 11,
        "local_segment_first": 12,
        "local_segment_last": 16,
        "local_done": 4,
        "legacy_gaps_ignored": 2,
        "physical_gaps_ignored": 1,
        "reused_number_markers": 1,
        "offloaded_first": 17,
        "offloaded_last": 20,
        "offloaded": 4,
        "reused_marker_first": 21,
        "reused_marker_last": 21,
        "new_pending_first": 22,
        "new_pending_last": 23,
        "new_pending": 2,
        "next_archive_number": 24,
        "total_rows": 12,
    }
    sample_mapping = {
        sample["archive_number"]: sample["old_export_position"]
        for sample in preview["samples"]
    }
    assert sample_mapping[12] == 5
    assert sample_mapping[14] == 7
    assert sample_mapping[15] == 9
    assert sample_mapping[16] == 10


def test_verified_windows_segments_map_exact_restart_boundary():
    segments, reused = legacy_bootstrap._build_segments(
        [
            {"start_id": 20968, "offset": 5833},
            {"start_id": 22315, "offset": 5832},
        ],
        tuple(range(20968, 23991)),
        old_count=18158,
        checkpoint_position=18158,
    )

    assert [segment.public() for segment in segments] == [
        {
            "start_id": 20968,
            "end_id": 22314,
            "offset": 5833,
            "first_position": 15135,
            "last_position": 16481,
        },
        {
            "start_id": 22315,
            "end_id": 23990,
            "offset": 5832,
            "first_position": 16483,
            "last_position": 18158,
        },
    ]
    assert reused == (16482,)


def test_piecewise_preview_rejects_unsafe_segments():
    with tempfile.TemporaryDirectory() as d:
        args, _segments = _piecewise_fixture(d)
        bad_cases = (
            ([{"start_id": 13, "offset": 7}, {"start_id": 15, "offset": 6}], "lowest local"),
            ([{"start_id": 12, "offset": 7}, {"start_id": 15, "offset": 8}], "overlap"),
            ([{"start_id": 12, "offset": 7}, {"start_id": 15, "offset": 7}], "checkpoint"),
            ([{"start_id": 12, "offset": 7}, {"start_id": 13, "offset": 6}], "existing MP4"),
        )
        for segments, message in bad_cases:
            try:
                legacy_bootstrap.plan_bootstrap(*args, mapping_segments=segments)
            except legacy_bootstrap.LegacyBootstrapError as exc:
                assert message in str(exc), (segments, str(exc))
            else:
                raise AssertionError(f"expected unsafe segment refusal: {segments}")


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
        "physical_gaps_ignored": 1,
        "reused_number_markers": 0,
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


def test_piecewise_apply_keeps_physical_and_reused_gaps_distinct():
    conn = store.init_db(store.connect(":memory:"))
    with tempfile.TemporaryDirectory() as d:
        args, segments = _piecewise_fixture(d)
        before = sorted(os.listdir(args[3]))
        plan = legacy_bootstrap.plan_bootstrap(*args, mapping_segments=segments)
        result = legacy_bootstrap.apply_bootstrap(conn, plan, plan.token)
        after = sorted(os.listdir(args[3]))

    assert before == after
    assert result == {
        "items_created": 12,
        "local_done": 4,
        "legacy_gaps_ignored": 2,
        "physical_gaps_ignored": 1,
        "reused_number_markers": 1,
        "offloaded": 4,
        "new_pending": 2,
        "next_archive_number": 24,
    }
    assert [row["id"] for row in store.all_items(conn)] == list(range(12, 24))
    assert store.get_item(conn, 12)["favorite_order"] == 5
    assert store.get_item(conn, 13)["favorite_order"] == 6
    assert store.get_item(conn, 13)["status"] == "ignored"
    assert "no local MP4" in store.get_item(conn, 13)["error"]
    assert store.get_item(conn, 14)["favorite_order"] == 7
    assert store.get_item(conn, 15)["favorite_order"] == 9
    assert store.get_item(conn, 16)["favorite_order"] == 10
    assert store.get_item(conn, 21)["favorite_order"] == 8
    assert store.get_item(conn, 21)["status"] == "ignored"
    assert "reused archive number" in store.get_item(conn, 21)["error"]
    assert store.get_item(conn, 22)["status"] == "pending"
    assert [row["id"] for row in store.page_items(conn, order="latest")] == [
        23, 22, 16, 15, 21, 14, 13, 12, 20, 19, 18, 17,
    ]


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
