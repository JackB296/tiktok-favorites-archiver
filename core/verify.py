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
        if row["status"] == "done" and f"{row['id']}.mp4" not in movies
    )
    orphans = sorted(
        (name for name in movies if int(name.split(".")[0]) not in known_ids),
        key=lambda name: int(name.split(".")[0]),
    )
    leftovers = sorted(name for name in files if name.endswith(_TEMP_SUFFIXES))

    return {
        "favorites": len(items),
        "done": sum(1 for row in items if row["status"] == "done"),
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
        if str(row["link"]).startswith("local://"):
            continue
        store.set_status(conn, row["id"], "pending")
        requeued += 1
    return {"requeued": requeued}
