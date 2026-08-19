"""Public username discovery and idempotent archive ingestion."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import profile_import, store


def _extractor(url):
    assert url == "https://www.tiktok.com/@cook"
    return {"entries": [
        {"id": "30000", "url": "https://www.tiktok.com/@cook/video/30000", "timestamp": 300, "description": "new", "uploader_id": "cook"},
        {"id": "20000", "url": "https://www.tiktok.com/@cook/video/20000", "timestamp": 200, "description": "middle", "uploader_id": "cook"},
        {
            "id": "10000", "url": "https://www.tiktok.com/@cook/video/10000",
            "webpage_url": "https://www.tiktok.com/@cook/video/10000",
            "timestamp": 100, "description": "old and complete", "title": "old",
            "uploader": "cook", "uploader_id": "creator-1", "uploader_url": "https://www.tiktok.com/@cook",
            "channel": "Cook Display", "duration": 12, "width": 1080, "height": 1920,
            "view_count": 1000, "like_count": 100, "comment_count": 10,
            "repost_count": 5, "save_count": 20,
        },
    ]}


def test_profile_import_normalizes_username_orders_oldest_first_and_is_idempotent():
    conn = store.init_db(store.connect(":memory:"))
    first = profile_import.import_profile(conn, "https://www.tiktok.com/@cook", extractor=_extractor)
    second = profile_import.import_profile(conn, "@cook", extractor=_extractor)

    assert first["discovered"] == first["added"] == 3
    assert second["added"] == 0 and second["existing"] == 3
    rows = store.all_items(conn)
    assert [row["link"].rsplit("/", 1)[-1] for row in rows] == ["10000", "20000", "30000"]
    assert rows[0]["caption"] == "old" and rows[0]["author"] == "Cook Display"
    assert rows[0]["description"] == "old and complete"
    assert rows[0]["creator_username"] == "cook"
    assert rows[0]["source_duration_s"] == 12
    assert (rows[0]["source_width"], rows[0]["source_height"]) == (1080, 1920)
    assert rows[0]["view_count"] == 1000 and rows[0]["save_count"] == 20
    assert rows[0]["favorited_at"] is None


def test_profile_import_rejects_invalid_or_empty_profiles():
    for value in ("bad/name", "https://example.com/@user", ""):
        try:
            profile_import.normalize_username(value)
        except profile_import.ProfileImportError:
            pass
        else:
            raise AssertionError(f"invalid username accepted: {value}")
    try:
        profile_import.discover_profile("cook", extractor=lambda _url: {"entries": []})
    except profile_import.ProfileImportError as error:
        assert "no public videos" in str(error)
    else:
        raise AssertionError("empty profile should fail")


def test_creator_policy_filters_backlog_keywords_and_reposts_without_changing_defaults():
    conn = store.init_db(store.connect(":memory:"))
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    def extractor(_url):
        return {"entries": [
            {"id": "3", "timestamp": now.timestamp(), "description": "daily pottery", "uploader": "cook", "is_repost": True},
            {"id": "2", "timestamp": now.timestamp(), "description": "daily pottery", "uploader": "cook"},
            {"id": "1", "timestamp": (now - timedelta(days=60)).timestamp(), "description": "daily pottery", "uploader": "cook"},
            {"id": "4", "timestamp": now.timestamp(), "description": "unrelated dance", "uploader": "cook"},
        ]}
    result = profile_import.import_profile(conn, "cook", extractor=extractor, now=now, policy={
        "archive_mode": "matching", "keywords": ["pottery"],
        "exclude_reposts": True, "max_backlog_days": 30,
    })
    assert result["discovered"] == 4 and result["matched"] == 1 and result["added"] == 1
    assert store.all_items(conn)[0]["link"].endswith("/2")


def test_monitored_creator_imports_full_backlog_then_only_adds_new_posts_when_due():
    conn = store.init_db(store.connect(":memory:"))
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    entries = _extractor("https://www.tiktok.com/@cook")["entries"]

    def extractor(_url):
        return {"entries": list(entries)}

    with tempfile.TemporaryDirectory() as downloads:
        initial = profile_import.monitor_profile(
            conn, "@cook", downloads, interval_hours=6,
            extractor=extractor, fetch=lambda _url, _target: False, now=now,
        )
        assert initial["added"] == 3
        monitor = store.list_creator_monitors(conn)[0]
        assert monitor["username"] == "cook" and monitor["enabled"] is True
        assert monitor["next_check_at"] == (now + timedelta(hours=6)).isoformat()

        entries.insert(0, {
            "id": "40000", "webpage_url": "https://www.tiktok.com/@cook/video/40000",
            "timestamp": 400, "description": "newest", "uploader": "cook",
        })
        assert profile_import.run_monitors(
            conn, downloads, extractor_factory=lambda _username: extractor,
            fetch=lambda _url, _target: False,
            now=now + timedelta(hours=5),
        ) == {"checked": 0, "added": 0, "failed": 0}
        refreshed = profile_import.run_monitors(
            conn, downloads, extractor_factory=lambda _username: extractor,
            fetch=lambda _url, _target: False,
            now=now + timedelta(hours=6),
        )

    assert refreshed == {"checked": 1, "added": 1, "failed": 0}
    assert len(store.all_items(conn)) == 4
    monitor = store.list_creator_monitors(conn)[0]
    assert monitor["last_new_count"] == 1 and monitor["last_error"] is None


if __name__ == "__main__":
    import traceback
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
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
