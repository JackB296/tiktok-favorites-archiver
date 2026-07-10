"""Resumable Gallery-index work for finished Archive media."""
import os

from core import media_index, store


def _fingerprint(path):
    stat = os.stat(path)
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _index_items(conn, download_dir, items, inspect, thumbnail_width, progress, should_continue):
    """Index a known set of finished items and report deterministic progress."""
    candidates = [
        item for item in items
        if os.path.isfile(os.path.join(download_dir, f"{item['id']}.mp4"))
    ]
    result = {"indexed": 0, "failed": 0}
    total = len(candidates)
    if progress:
        progress({"event": "indexing", "indexed": 0, "failed": 0, "completed": 0, "total": total})
    for completed, item in enumerate(candidates, start=1):
        if should_continue and not should_continue():
            break
        movie = os.path.join(download_dir, f"{item['id']}.mp4")
        try:
            index = inspect(download_dir, item["id"], thumbnail_width)
            store.record_media_index(conn, item["id"], index._asdict(), _fingerprint(movie))
            result["indexed"] += 1
        except Exception as error:
            store.record_media_index_error(conn, item["id"], str(error))
            result["failed"] += 1
        if progress:
            progress({"event": "indexing", **result, "completed": completed, "total": total})
    return result


def index_pending_items(conn, download_dir, inspect=media_index.index_media, thumbnail_width=480, progress=None, should_continue=None):
    """Index finished Archive items without a durable thumbnail yet."""
    return _index_items(
        conn,
        download_dir,
        store.items_needing_index(conn),
        inspect,
        thumbnail_width,
        progress,
        should_continue,
    )


def rebuild_index(conn, download_dir, inspect=media_index.index_media, thumbnail_width=480, progress=None, should_continue=None):
    """Regenerate Gallery facts and thumbnails for every finished local video."""
    return _index_items(
        conn,
        download_dir,
        store.items_by_status(conn, ["done"]),
        inspect,
        thumbnail_width,
        progress,
        should_continue,
    )
