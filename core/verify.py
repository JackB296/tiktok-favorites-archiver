"""Archive integrity report: the database versus the files on disk (stdlib).

``verify_archive`` reports three failure classes — finished items whose video
is missing from disk, video files no item claims, and leftover temp files from
crashed downloads or encodes — and records the missing set as durable
``archive_missing`` flags so the Gallery recovery filter can select them.
``requeue_missing`` is the one explicit repair: finished-but-fileless
favorites go back to ``pending`` so the next Sync re-downloads them.
User-directed lifecycle changes (marks, selected requeues) live in
``core/curation``.
"""
import os

from core import layout, store

_EXAMPLE_LIMIT = 50


def _summarize(values):
    return {"count": len(values), "examples": values[:_EXAMPLE_LIMIT]}


def verify_archive(conn, download_dir):
    """Compare Archive items against the download directory."""
    items = store.all_items(conn)
    files = os.listdir(download_dir) if os.path.isdir(download_dir) else []
    movies = set(layout.finished_movie_ids(files))
    known_ids = {row["id"] for row in items}

    missing = sorted(
        row["id"] for row in items
        if row["status"] == "done" and not row["offloaded"] and row["id"] not in movies
    )
    store.record_archive_file_health(conn, missing)
    orphans = [f"{n}.mp4" for n in sorted(movies - known_ids)]
    leftovers = sorted(name for name in files if name.endswith(layout.TEMP_SUFFIXES))

    return {
        "favorites": len(items),
        "done": sum(1 for row in items if row["status"] == "done"),
        "offloaded": sum(1 for row in items if row["offloaded"]),
        "missing": _summarize(missing),
        "orphans": _summarize(orphans),
        "leftovers": _summarize(leftovers),
        "ok": not (missing or orphans or leftovers),
    }


def requeue_missing(conn, download_dir):
    """Reset finished-but-fileless favorites to pending for the next Sync.

    Items with synthetic ``local://`` links are skipped — they exist only to
    represent a file, so with the file gone there is nothing to re-download.
    """
    files = os.listdir(download_dir) if os.path.isdir(download_dir) else []
    movies = set(layout.finished_movie_ids(files))
    requeued = 0
    for row in store.all_items(conn):
        if row["status"] != "done" or row["id"] in movies:
            continue
        if not store.is_redownloadable(row):
            continue
        store.set_status(conn, row["id"], "pending")
        requeued += 1
    return {"requeued": requeued}


def offload_suggestion(conn, download_dir):
    """Suggest the 'everything below my earliest local file' offload range."""
    files = os.listdir(download_dir) if os.path.isdir(download_dir) else []
    numbers = layout.finished_movie_ids(files)
    if not numbers or numbers[0] <= 1:
        return {
            "earliest_local": numbers[0] if numbers else None,
            "suggested": None,
            "range_total": 0,
            "range_undownloaded": 0,
            "range_already_offloaded": 0,
        }
    first, last = 1, numbers[0] - 1
    summary = store.range_status_summary(conn, first, last)
    return {
        "earliest_local": numbers[0],
        "suggested": {"first_id": first, "last_id": last},
        "range_total": summary["total"],
        "range_undownloaded": summary["undownloaded"],
        "range_already_offloaded": summary["already_offloaded"],
    }
