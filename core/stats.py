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


def compute_stats(conn):
    """The full `/api/stats` payload: one dict, JSON-ready."""
    return {
        "hero": _hero(conn),
        "growth": _growth(conn),
        "watcher": _watcher(conn),
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

    durations = [
        r["duration_s"]
        for r in conn.execute(
            "SELECT duration_s FROM item WHERE duration_s IS NOT NULL ORDER BY duration_s"
        ).fetchall()
    ]
    histogram = []
    for label, lo, hi in DURATION_BUCKETS:
        count = sum(1 for d in durations if d >= lo and (hi is None or d < hi))
        histogram.append({"label": label, "count": count})
    if not durations:
        histogram = []
        median = None
    else:
        mid = len(durations) // 2
        median = durations[mid] if len(durations) % 2 else (durations[mid - 1] + durations[mid]) / 2.0

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
