"""Archive integrity report: the database versus the files on disk (stdlib).

Read-only by default. ``verify_archive`` reports three failure classes:
finished items whose video is missing from disk, video files no item claims,
and leftover temp files from crashed downloads or encodes. ``requeue_missing``
is the one explicit repair: finished-but-fileless favorites go back to
``pending`` so the next Sync re-downloads them.
"""
import os

from core import store

_EXAMPLE_LIMIT = 50
_TEMP_SUFFIXES = (".part", ".part.mp4", ".tmp")


def _summarize(values):
    return {"count": len(values), "examples": values[:_EXAMPLE_LIMIT]}


def _finished_movie_names(files):
    names = set()
    for name in files:
        stem = name.split(".")[0]
        if stem.isdigit() and name == f"{stem}.mp4":
            names.add(name)
    return names


def verify_archive(conn, download_dir):
    """Compare Archive items against the download directory."""
    items = store.all_items(conn)
    files = os.listdir(download_dir) if os.path.isdir(download_dir) else []
    movies = _finished_movie_names(files)
    known_ids = {row["id"] for row in items}

    missing = sorted(
        row["id"] for row in items
        if row["status"] == "done" and not row["offloaded"] and f"{row['id']}.mp4" not in movies
    )
    store.record_archive_file_health(conn, missing)
    orphans = sorted(
        (name for name in movies if int(name.split(".")[0]) not in known_ids),
        key=lambda name: int(name.split(".")[0]),
    )
    leftovers = sorted(name for name in files if name.endswith(_TEMP_SUFFIXES))

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
    movies = _finished_movie_names(files)
    requeued = 0
    for row in store.all_items(conn):
        if row["status"] != "done" or f"{row['id']}.mp4" in movies:
            continue
        if str(row["link"]).startswith("local://") or row["offloaded"]:
            continue
        store.set_status(conn, row["id"], "pending")
        requeued += 1
    return {"requeued": requeued}


def requeue_selected(conn, download_dir, item_ids):
    """Queue explicitly selected recoverable items for the next Sync.

    A failed remote favorite is retryable. A finished remote favorite is only
    retryable when its numbered video is actually gone. This intentionally
    leaves healthy, in-progress, and synthetic local placeholders unchanged.
    """
    files = os.listdir(download_dir) if os.path.isdir(download_dir) else []
    movies = _finished_movie_names(files)
    rows = {row["id"]: row for row in store.all_items(conn)}
    requested = list(dict.fromkeys(item_ids))
    requeued = []
    for item_id in requested:
        row = rows.get(item_id)
        if row is None or str(row["link"]).startswith("local://") or row["offloaded"]:
            continue
        missing_done_file = row["status"] == "done" and f"{item_id}.mp4" not in movies
        if row["status"] != "failed" and not missing_done_file:
            continue
        store.set_status(conn, item_id, "pending")
        requeued.append(item_id)
    return {"requeued": requeued, "skipped": len(requested) - len(requeued)}


def offload_suggestion(conn, download_dir):
    """Suggest the 'everything below my earliest local file' offload range."""
    files = os.listdir(download_dir) if os.path.isdir(download_dir) else []
    numbers = sorted(int(name.split(".")[0]) for name in _finished_movie_names(files))
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
