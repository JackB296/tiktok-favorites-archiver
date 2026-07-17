"""Tests for core.stats — archive analytics aggregates (stdlib sqlite3)."""
import os
import sys

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
