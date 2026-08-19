"""Tests for core.stats — archive analytics aggregates (stdlib sqlite3)."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import stats, store


def _db():
    conn = store.connect(":memory:")
    return store.init_db(conn)


def _index(conn, item_id, duration_s=10.0, width=1080, height=1920, codec="h264",
           file_size=1000, has_audio=True, audio_silent=False):
    store.record_media_index(conn, item_id, {
        "thumbnail_path": f"/t/{item_id}.webp",
        "duration_s": duration_s,
        "width": width,
        "height": height,
        "codec": codec,
        "file_size": file_size,
        "has_audio": has_audio,
        "audio_silent": audio_silent,
    }, fingerprint=f"fp-{item_id}")


def test_empty_library_returns_zeroed_shapes():
    s = stats.compute_stats(_db())
    assert s["hero"]["total"] == 0
    assert s["hero"]["archived"] == 0
    assert s["hero"]["disk_bytes"] == 0
    assert s["hero"]["watch_seconds"] == 0
    assert s["growth"]["monthly"] == []
    assert s["watcher"]["heatmap"] == []
    assert s["watcher"]["duration_histogram"] == []
    assert s["top"]["authors"] == []
    assert s["top"]["songs"] == []
    assert s["top"]["hashtags"] == []
    assert s["health"]["statuses"] == {}


def test_hero_counts_media_totals_and_disclosures():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", favorited_at="2023-05-01 10:00:00",
                      kind="video", status="done")
    _index(conn, 1, duration_s=30.0, file_size=2000)
    # done but never indexed: counted, disclosed as unindexed
    store.insert_item(conn, 2, "https://tiktok.com/b", favorited_at="2023-06-01 10:00:00",
                      kind="slideshow", status="done")
    # pending and undated: still part of the library
    store.insert_item(conn, 3, "https://tiktok.com/c", kind="video", status="pending")
    # offloaded done item counts as archived
    store.insert_item(conn, 4, "https://tiktok.com/d", favorited_at="2023-06-02 10:00:00",
                      kind="video", status="done")
    conn.execute("UPDATE item SET offloaded = 1 WHERE id = 4")
    conn.commit()

    hero = stats.compute_stats(conn)["hero"]
    assert hero["total"] == 4
    assert hero["videos"] == 3 and hero["slideshows"] == 1
    assert hero["archived"] == 3
    assert hero["archived_pct"] == 75.0
    assert hero["watch_seconds"] == 30.0
    assert hero["disk_bytes"] == 2000
    assert hero["undated"] == 1
    assert hero["unindexed"] == 2  # items 2 and 4 are done without media facts


def test_growth_buckets_by_month_and_skips_undated():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", favorited_at="2023-05-01 10:00:00")
    store.insert_item(conn, 2, "https://tiktok.com/b", favorited_at="2023-05-20 22:00:00")
    store.insert_item(conn, 3, "https://tiktok.com/c", favorited_at="2023-07-04 08:00:00")
    store.insert_item(conn, 4, "https://tiktok.com/d")  # undated: excluded, disclosed in hero

    growth = stats.compute_stats(conn)["growth"]
    assert growth["monthly"] == [
        {"month": "2023-05", "count": 2},
        {"month": "2023-07", "count": 1},
    ]


def test_watcher_heatmap_histogram_median_and_silent():
    conn = _db()
    # 2023-05-01 is a Monday (dow 1); 2023-05-07 is a Sunday (dow 0)
    store.insert_item(conn, 1, "https://tiktok.com/a", favorited_at="2023-05-01 10:15:00",
                      kind="video", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/b", favorited_at="2023-05-01 10:45:00",
                      kind="video", status="done")
    store.insert_item(conn, 3, "https://tiktok.com/c", favorited_at="2023-05-07 23:05:00",
                      kind="video", status="done")
    _index(conn, 1, duration_s=8.0, audio_silent=True)
    _index(conn, 2, duration_s=45.0)
    _index(conn, 3, duration_s=200.0)

    watcher = stats.compute_stats(conn)["watcher"]
    cells = {(c["dow"], c["hour"]): c["count"] for c in watcher["heatmap"]}
    assert cells[(1, 10)] == 2
    assert cells[(0, 23)] == 1
    buckets = {b["label"]: b["count"] for b in watcher["duration_histogram"]}
    assert buckets["0–15s"] == 1
    assert buckets["30–60s"] == 1
    assert buckets["2–5m"] == 1
    assert watcher["median_duration_s"] == 45.0
    assert watcher["silent"] == {"count": 1, "of_indexed": 3}


def test_top_authors_songs_and_hashtags_count_favorites():
    conn = _db()
    for i, (author, caption) in enumerate([
        ("alice", "fun #cats #cats and more"),   # duplicate tag in one caption counts once
        ("alice", "again #cats"),
        ("bob", "hello #dogs"),
        (None, "no author #dogs"),
    ], start=1):
        store.insert_item(conn, i, f"https://tiktok.com/{i}", kind="video", status="done")
        conn.execute("UPDATE item SET author = ?, caption = ? WHERE id = ?", (author, caption, i))
    conn.commit()
    song = store.upsert_song(conn, "ta:song|artist", "Song", artist="Artist")
    store.set_item_song(conn, 1, song, source="auto")
    store.set_item_song(conn, 2, song, source="manual")

    top = stats.compute_stats(conn)["top"]
    assert top["authors"][0] == {"author": "alice", "count": 2}
    assert {"author": "bob", "count": 1} in top["authors"]
    assert top["songs"][0]["title"] == "Song"
    assert top["songs"][0]["count"] == 2
    assert top["hashtags"][0] == {"tag": "#cats", "count": 2}
    assert {"tag": "#dogs", "count": 2} in top["hashtags"]


def test_health_statuses_flags_and_top_errors():
    conn = _db()
    store.insert_item(conn, 1, "https://tiktok.com/a", status="done")
    store.insert_item(conn, 2, "https://tiktok.com/b", status="failed")
    store.insert_item(conn, 3, "https://tiktok.com/c", status="failed")
    store.insert_item(conn, 4, "https://tiktok.com/d", status="ignored")
    conn.execute("UPDATE item SET error = 'HTTP 429' WHERE id = 2")
    conn.execute("UPDATE item SET error = 'HTTP 429' WHERE id = 3")
    conn.execute("UPDATE item SET archive_missing = 1 WHERE id = 1")
    conn.commit()

    health = stats.compute_stats(conn)["health"]
    assert health["statuses"] == {"done": 1, "failed": 2, "ignored": 1}
    assert health["missing"] == 1
    assert health["errors"][0] == {"error": "HTTP 429", "count": 2}


def test_source_reach_save_lag_and_peak_posts_are_aggregated_and_bounded():
    conn = _db()
    for item_id in range(1, 9):
        store.insert_item(
            conn, item_id, f"https://tiktok.com/{item_id}",
            favorited_at="2026-07-08 12:00:00", kind="video", status="done",
        )
        conn.execute(
            "UPDATE item SET description = ?, creator_username = ?, "
            "source_posted_at = ?, view_count = ?, like_count = ?, "
            "comment_count = ?, repost_count = ?, save_count = ? WHERE id = ?",
            (
                (f"Post {item_id} " + "x" * 400), f"creator{item_id}",
                "2026-07-01T12:00:00+00:00" if item_id == 1
                else "2026-07-08T06:00:00+00:00",
                item_id * 1000, item_id * 100, item_id * 10,
                item_id * 5, item_id * 2, item_id,
            ),
        )
    conn.commit()

    result = stats.compute_stats(conn)
    assert result["reach"] == {
        "covered": 8,
        "views": 36000,
        "likes": 3600,
        "comments": 360,
        "reposts": 180,
        "saves": 72,
        "peak_posts": result["reach"]["peak_posts"],
    }
    peaks = result["reach"]["peak_posts"]
    assert len(peaks) == 5
    assert peaks[0]["id"] == 8 and peaks[0]["views"] == 8000
    assert peaks[0]["creator"] == "creator8"
    assert len(peaks[0]["caption"]) <= 160
    assert result["discovery_lag"] == {
        "covered": 8,
        "buckets": [
            {"label": "Same day", "count": 7},
            {"label": "Within a week", "count": 0},
            {"label": "Within a month", "count": 1},
            {"label": "Later", "count": 0},
        ],
    }


def test_offline_depth_video_quality_comments_and_creator_radar():
    conn = _db()
    for item_id, width, height in (
        (1, 2160, 3840), (2, 1080, 1920), (3, 720, 1280), (4, 576, 1024),
    ):
        store.insert_item(conn, item_id, f"https://tiktok.com/{item_id}",
                          kind="video", status="done")
        _index(conn, item_id, width=width, height=height)
    conn.execute(
        "UPDATE item SET source_info_status = 'ok', comments_status = 'ok', "
        "source_thumbnail_path = 'source/1.webp', portable_metadata_status = 'ok', "
        "download_source = 'yt-dlp' WHERE id = 1"
    )
    conn.execute("UPDATE item SET download_source = 'cobalt' WHERE id IN (2, 3)")
    conn.execute("UPDATE item SET comments_status = 'ok' WHERE id = 2")
    conn.commit()

    store.record_comment_snapshot(
        conn, 1, [{"id": "a", "text": "first"}, {"id": "b", "text": "second"}],
        captured_at="2026-07-01T12:00:00+00:00",
    )
    store.record_comment_snapshot(
        conn, 1, [{"id": "a", "text": "edited"}, {"id": "c", "text": "new"}],
        captured_at="2026-07-02T12:00:00+00:00",
    )
    store.record_comment_snapshot(
        conn, 2, [{"id": "d", "text": "other post"}],
        captured_at="2026-07-02T13:00:00+00:00",
    )
    active = store.save_creator_monitor(
        conn, "alice", interval_hours=6,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    store.mark_creator_monitor_checked(
        conn, active["id"], added=3, error=None,
        now=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )
    store.save_creator_monitor(
        conn, "bob", interval_hours=12, enabled=False,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    result = stats.compute_stats(conn)
    assert result["quality"]["resolution"] == [
        {"label": "4K", "count": 1},
        {"label": "1080p", "count": 1},
        {"label": "720p", "count": 1},
        {"label": "Lower", "count": 1},
    ]
    assert result["quality"]["downloads"] == [
        {"label": "Cobalt", "count": 2},
        {"label": "yt-dlp", "count": 1},
        {"label": "Legacy / unknown", "count": 1},
    ]
    assert result["quality"]["offline"] == {
        "total": 4,
        "source_metadata": 1,
        "comments": 2,
        "thumbnails": 4,
        "portable_metadata": 1,
        "songs": 0,
    }
    assert result["conversation"] == {
        "posts": 2,
        "snapshots": 3,
        "saved_comments": 3,
        "changes": {"added": 1, "removed": 1, "changed": 1},
    }
    assert result["monitoring"] == {
        "profiles": 2,
        "active": 1,
        "checked": 1,
        "found_last_check": 3,
        "errors": 0,
    }


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
