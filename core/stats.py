"""Archive analytics aggregates for the Stats tab (stdlib sqlite3).

Every number is computed on demand from columns the archive already maintains
— no schema, no caching, no background work. Items without a value for a
dimension (undated favorites, unindexed media) are excluded from that chart
and disclosed as counts, never guessed.
"""
import re

from core import discovery, migrations

# Fixed duration buckets: label + inclusive lower / exclusive upper bound (s).
DURATION_BUCKETS = (
    ("0–15s", 0, 15),
    ("15–30s", 15, 30),
    ("30–60s", 30, 60),
    ("1–2m", 60, 120),
    ("2–5m", 120, 300),
    ("5m+", 300, None),
)

TOP_LIMIT = 15
ERROR_LIMIT = 8
PEAK_POST_LIMIT = 5


def compute_stats(conn):
    """The full `/api/stats` payload: one dict, JSON-ready."""
    return {
        "hero": _hero(conn),
        "growth": _growth(conn),
        "watcher": _watcher(conn),
        "reach": _reach(conn),
        "discovery_lag": _discovery_lag(conn),
        "quality": _quality(conn),
        "conversation": _conversation(conn),
        "monitoring": _monitoring(conn),
        "top": _top(conn),
        "health": _health(conn),
    }


def _hero(conn):
    row = conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(kind = 'video') AS videos,"
        " SUM(kind = 'slideshow') AS slideshows,"
        " SUM(status = 'done') AS archived,"
        " COALESCE(SUM(duration_s), 0) AS watch_seconds,"
        " COALESCE(SUM(media_size), 0) AS disk_bytes,"
        " SUM(favorited_at IS NULL) AS undated,"
        " SUM(status = 'done' AND indexed_at IS NULL) AS unindexed "
        "FROM item"
    ).fetchone()
    total = row["total"]
    archived = row["archived"] or 0
    return {
        "total": total,
        "videos": row["videos"] or 0,
        "slideshows": row["slideshows"] or 0,
        "archived": archived,
        "archived_pct": round(archived * 100.0 / total, 1) if total else 0.0,
        "watch_seconds": row["watch_seconds"],
        "disk_bytes": row["disk_bytes"],
        "undated": row["undated"] or 0,
        "unindexed": row["unindexed"] or 0,
    }


def _growth(conn):
    monthly = [
        {"month": r["month"], "count": r["c"]}
        for r in conn.execute(
            "SELECT substr(favorited_at, 1, 7) AS month, COUNT(*) AS c FROM item "
            "WHERE favorited_at IS NOT NULL GROUP BY month ORDER BY month"
        ).fetchall()
    ]
    return {"monthly": monthly}


def _watcher(conn):
    heatmap = [
        {"dow": int(r["dow"]), "hour": int(r["hour"]), "count": r["c"]}
        for r in conn.execute(
            # %w: 0 = Sunday. favorited_at is 'YYYY-MM-DD HH:MM:SS' from the export.
            "SELECT strftime('%w', favorited_at) AS dow, strftime('%H', favorited_at) AS hour,"
            " COUNT(*) AS c FROM item WHERE favorited_at IS NOT NULL"
            " GROUP BY dow, hour"
        ).fetchall()
        if r["dow"] is not None and r["hour"] is not None
    ]

    # Bucket in SQLite instead of transferring every duration to Python. The
    # partial duration index also makes the two-row median lookup inexpensive.
    durations = conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(duration_s >= 0 AND duration_s < 15) AS b0,"
        " SUM(duration_s >= 15 AND duration_s < 30) AS b1,"
        " SUM(duration_s >= 30 AND duration_s < 60) AS b2,"
        " SUM(duration_s >= 60 AND duration_s < 120) AS b3,"
        " SUM(duration_s >= 120 AND duration_s < 300) AS b4,"
        " SUM(duration_s >= 300) AS b5 "
        "FROM item WHERE duration_s IS NOT NULL"
    ).fetchone()
    duration_count = durations["total"]
    histogram = [
        {"label": bucket[0], "count": durations[f"b{index}"] or 0}
        for index, bucket in enumerate(DURATION_BUCKETS)
    ]
    if not duration_count:
        histogram = []
        median = None
    else:
        middle = conn.execute(
            "SELECT AVG(duration_s) AS median FROM ("
            " SELECT duration_s FROM item WHERE duration_s IS NOT NULL"
            " ORDER BY duration_s LIMIT ? OFFSET ?"
            ")",
            (2 if duration_count % 2 == 0 else 1, (duration_count - 1) // 2),
        ).fetchone()
        median = middle["median"]

    # Only videos carry a silence verdict — slideshows are rebuilt with audio
    # and leave audio_silent NULL, so counting them would dilute the share and
    # mislabel the "of N indexed videos" denominator.
    silent = conn.execute(
        "SELECT SUM(audio_silent = 1) AS silent, COUNT(*) AS indexed "
        "FROM item WHERE indexed_at IS NOT NULL AND kind = 'video'"
    ).fetchone()
    return {
        "heatmap": heatmap,
        "duration_histogram": histogram,
        "median_duration_s": median,
        "silent": {"count": silent["silent"] or 0, "of_indexed": silent["indexed"]},
    }


def _reach(conn):
    """Bounded source engagement summary plus five local playback links."""
    row = conn.execute(
        "SELECT COUNT(view_count) AS covered,"
        " COALESCE(SUM(view_count), 0) AS views,"
        " COALESCE(SUM(like_count), 0) AS likes,"
        " COALESCE(SUM(comment_count), 0) AS comments,"
        " COALESCE(SUM(repost_count), 0) AS reposts,"
        " COALESCE(SUM(save_count), 0) AS saves FROM item"
    ).fetchone()
    peaks = [
        {
            "id": result["id"], "caption": result["caption"],
            "creator": result["creator"], "views": result["views"] or 0,
            "likes": result["likes"] or 0,
            "comments": result["comments"] or 0,
            "reposts": result["reposts"] or 0,
            "saves": result["saves"] or 0,
        }
        for result in conn.execute(
            "SELECT id, SUBSTR(COALESCE(NULLIF(description, ''), NULLIF(caption, ''),"
            " 'Favorite #' || id), 1, 160) AS caption,"
            " COALESCE(NULLIF(creator_username, ''), NULLIF(author, '')) AS creator,"
            " view_count AS views, like_count AS likes, comment_count AS comments,"
            " repost_count AS reposts, save_count AS saves FROM item "
            "WHERE view_count IS NOT NULL ORDER BY view_count DESC, like_count DESC, id "
            "LIMIT ?",
            (PEAK_POST_LIMIT,),
        ).fetchall()
    ]
    return {
        "covered": row["covered"], "views": row["views"], "likes": row["likes"],
        "comments": row["comments"], "reposts": row["reposts"], "saves": row["saves"],
        "peak_posts": peaks,
    }


def _discovery_lag(conn):
    """How soon after publication a post was favorited, in fixed buckets."""
    row = conn.execute(
        "WITH lagged AS ("
        " SELECT julianday(favorited_at) - julianday(source_posted_at) AS days"
        " FROM item WHERE favorited_at IS NOT NULL AND source_posted_at IS NOT NULL"
        "), valid AS (SELECT days FROM lagged WHERE days IS NOT NULL AND days >= -1) "
        "SELECT COUNT(*) AS covered,"
        " SUM(days < 1) AS same_day,"
        " SUM(days >= 1 AND days < 7) AS week,"
        " SUM(days >= 7 AND days < 30) AS month,"
        " SUM(days >= 30) AS later FROM valid"
    ).fetchone()
    covered = row["covered"]
    return {
        "covered": covered,
        "buckets": [] if not covered else [
            {"label": "Same day", "count": row["same_day"] or 0},
            {"label": "Within a week", "count": row["week"] or 0},
            {"label": "Within a month", "count": row["month"] or 0},
            {"label": "Later", "count": row["later"] or 0},
        ],
    }


def _quality(conn):
    """Offline completeness, archived resolution, and bounded downloader mix."""
    row = conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(source_info_status = 'ok') AS source_metadata,"
        " SUM(comments_status = 'ok') AS comments,"
        " SUM(COALESCE(custom_thumbnail_path, thumbnail_path, source_thumbnail_path) IS NOT NULL)"
        " AS thumbnails,"
        " SUM(portable_metadata_status = 'ok') AS portable_metadata,"
        " SUM(song_id IS NOT NULL) AS songs,"
        " SUM(download_source = 'cobalt') AS cobalt,"
        " SUM(download_source = 'yt-dlp') AS ytdlp,"
        " SUM(download_source IS NULL OR download_source NOT IN ('cobalt', 'yt-dlp')) AS legacy "
        "FROM item"
    ).fetchone()
    resolution = conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(MIN(media_width, media_height) >= 2160) AS r4k,"
        " SUM(MIN(media_width, media_height) >= 1080"
        "     AND MIN(media_width, media_height) < 2160) AS r1080,"
        " SUM(MIN(media_width, media_height) >= 720"
        "     AND MIN(media_width, media_height) < 1080) AS r720,"
        " SUM(MIN(media_width, media_height) < 720) AS lower "
        "FROM item WHERE kind = 'video' AND media_width > 0 AND media_height > 0"
    ).fetchone()
    return {
        "offline": {
            "total": row["total"],
            "source_metadata": row["source_metadata"] or 0,
            "comments": row["comments"] or 0,
            "thumbnails": row["thumbnails"] or 0,
            "portable_metadata": row["portable_metadata"] or 0,
            "songs": row["songs"] or 0,
        },
        "resolution": [] if not resolution["total"] else [
            {"label": "4K", "count": resolution["r4k"] or 0},
            {"label": "1080p", "count": resolution["r1080"] or 0},
            {"label": "720p", "count": resolution["r720"] or 0},
            {"label": "Lower", "count": resolution["lower"] or 0},
        ],
        "downloads": [
            {"label": "Cobalt", "count": row["cobalt"] or 0},
            {"label": "yt-dlp", "count": row["ytdlp"] or 0},
            {"label": "Legacy / unknown", "count": row["legacy"] or 0},
        ],
    }


def _conversation(conn):
    """Comment history without loading or parsing any saved comment JSON."""
    row = conn.execute(
        "WITH bounds AS ("
        " SELECT item_id, MIN(id) AS first_id, MAX(id) AS latest_id"
        " FROM comment_snapshot GROUP BY item_id"
        ") SELECT COUNT(DISTINCT current.item_id) AS posts, COUNT(*) AS snapshots,"
        " COALESCE(SUM(CASE WHEN current.id = bounds.latest_id"
        " THEN current.saved_count ELSE 0 END), 0) AS saved_comments,"
        " COALESCE(SUM(CASE WHEN current.id != bounds.first_id"
        " THEN current.added_count ELSE 0 END), 0) AS added,"
        " COALESCE(SUM(CASE WHEN current.id != bounds.first_id"
        " THEN current.removed_count ELSE 0 END), 0) AS removed,"
        " COALESCE(SUM(CASE WHEN current.id != bounds.first_id"
        " THEN current.changed_count ELSE 0 END), 0) AS changed "
        "FROM comment_snapshot current JOIN bounds ON bounds.item_id = current.item_id"
    ).fetchone()
    return {
        "posts": row["posts"] or 0,
        "snapshots": row["snapshots"],
        "saved_comments": row["saved_comments"],
        "changes": {
            "added": row["added"], "removed": row["removed"],
            "changed": row["changed"],
        },
    }


def _monitoring(conn):
    row = conn.execute(
        "SELECT COUNT(*) AS profiles, SUM(enabled = 1) AS active,"
        " SUM(last_checked_at IS NOT NULL) AS checked,"
        " COALESCE(SUM(last_new_count), 0) AS found_last_check,"
        " SUM(last_error IS NOT NULL) AS errors FROM creator_monitor"
    ).fetchone()
    return {
        "profiles": row["profiles"], "active": row["active"] or 0,
        "checked": row["checked"] or 0,
        "found_last_check": row["found_last_check"], "errors": row["errors"] or 0,
    }


def _top(conn):
    state = migrations.get_backfill(conn, discovery.BACKFILL)
    identities_ready = state is not None and state["status"] == "completed"
    if identities_ready:
        authors = [
            {"author": r["display_name"], "count": r["use_count"]}
            for r in conn.execute(
                "SELECT c.display_name, COUNT(*) AS use_count FROM item i "
                "JOIN creator c ON c.id = i.creator_id GROUP BY c.id "
                "ORDER BY use_count DESC, c.display_name LIMIT ?", (TOP_LIMIT,),
            ).fetchall()
        ]
    else:
        authors = [
            {"author": r["author"], "count": r["c"]}
            for r in conn.execute(
                "SELECT author, COUNT(*) AS c FROM item "
                "WHERE author IS NOT NULL AND author != '' "
                "GROUP BY author ORDER BY c DESC, author LIMIT ?",
                (TOP_LIMIT,),
            ).fetchall()
        ]
    songs = [
        {"id": r["id"], "title": r["title"], "artist": r["artist"], "count": r["c"]}
        for r in conn.execute(
            "SELECT song.id AS id, song.title AS title, song.artist AS artist, COUNT(*) AS c "
            "FROM item JOIN song ON item.song_id = song.id "
            "GROUP BY song.id ORDER BY c DESC, song.title LIMIT ?",
            (TOP_LIMIT,),
        ).fetchall()
    ]

    # Hashtags count favorites containing the tag (a tag repeated in one
    # caption counts once) — same tag shape the search suggestions use.
    if identities_ready:
        hashtags = [
            {"tag": r["display_name"], "count": r["use_count"]}
            for r in conn.execute(
                "SELECT h.display_name, COUNT(*) AS use_count FROM item_hashtag ih "
                "JOIN hashtag h ON h.id = ih.hashtag_id GROUP BY h.id "
                "ORDER BY use_count DESC, h.display_name LIMIT ?", (TOP_LIMIT,),
            ).fetchall()
        ]
    else:
        counts = {}
        for r in conn.execute(
            "SELECT caption FROM item WHERE caption IS NOT NULL AND caption != ''"
        ).fetchall():
            for tag in set(re.findall(r"#(\w+)", r["caption"].lower())):
                counts[tag] = counts.get(tag, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        hashtags = [{"tag": "#" + tag, "count": c} for tag, c in ranked[:TOP_LIMIT]]

    return {"authors": authors, "songs": songs, "hashtags": hashtags}


def _health(conn):
    statuses = {
        r["status"]: r["c"]
        for r in conn.execute("SELECT status, COUNT(*) AS c FROM item GROUP BY status").fetchall()
    }
    flags = conn.execute(
        "SELECT SUM(archive_missing = 1) AS missing, SUM(offloaded = 1) AS offloaded FROM item"
    ).fetchone()
    errors = [
        {"error": r["error"], "count": r["c"]}
        for r in conn.execute(
            "SELECT error, COUNT(*) AS c FROM item "
            "WHERE status = 'failed' AND error IS NOT NULL "
            "GROUP BY error ORDER BY c DESC, error LIMIT ?",
            (ERROR_LIMIT,),
        ).fetchall()
    ]
    return {
        "statuses": statuses,
        "missing": flags["missing"] or 0,
        "offloaded": flags["offloaded"] or 0,
        "errors": errors,
    }
