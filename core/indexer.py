"""Resumable Gallery-index work for finished Archive media."""
import os
from concurrent.futures import ThreadPoolExecutor

from core import media_index, store


def _fingerprint(path):
    stat = os.stat(path)
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _default_workers():
    return min(4, os.cpu_count() or 1)


def _index_items(conn, download_dir, items, inspect, thumbnail_width, progress, should_continue, workers=None):
    """Index a known set of finished items and report deterministic progress.

    The ffprobe/ffmpeg inspection runs on a bounded worker pool (a full rebuild
    is otherwise pinned to one core for tens of minutes); all database writes
    stay on the calling thread, batch by batch, so no connection is shared
    across threads. Pause/stop is honored between batches.
    """
    candidates = [
        item for item in items
        if os.path.isfile(os.path.join(download_dir, f"{item['id']}.mp4"))
    ]
    result = {"indexed": 0, "failed": 0}
    total = len(candidates)
    completed = 0
    if progress:
        progress({"event": "indexing", "indexed": 0, "failed": 0, "completed": 0, "total": total})
    workers = workers or _default_workers()

    def record(item, future_result):
        nonlocal completed
        try:
            index = future_result()
            movie = os.path.join(download_dir, f"{item['id']}.mp4")
            store.record_media_index(conn, item["id"], index._asdict(), _fingerprint(movie))
            result["indexed"] += 1
        except Exception as error:
            store.record_media_index_error(conn, item["id"], str(error))
            result["failed"] += 1
        completed += 1
        if progress:
            progress({"event": "indexing", **result, "completed": completed, "total": total})

    if workers <= 1:
        for item in candidates:
            if should_continue and not should_continue():
                break
            record(item, lambda item=item: inspect(download_dir, item["id"], thumbnail_width))
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, total, workers):
            if should_continue and not should_continue():
                break
            batch = candidates[start:start + workers]
            futures = [
                (item, pool.submit(inspect, download_dir, item["id"], thumbnail_width))
                for item in batch
            ]
            for item, future in futures:
                record(item, future.result)
    return result


def index_pending_items(conn, download_dir, inspect=media_index.index_media, thumbnail_width=480, progress=None, should_continue=None, workers=None):
    """Index finished Archive items without a durable thumbnail yet."""
    return _index_items(
        conn,
        download_dir,
        store.items_needing_index(conn),
        inspect,
        thumbnail_width,
        progress,
        should_continue,
        workers=workers,
    )


def rebuild_index(conn, download_dir, inspect=media_index.index_media, thumbnail_width=480, progress=None, should_continue=None, workers=None):
    """Regenerate Gallery facts and thumbnails for every finished local video."""
    return _index_items(
        conn,
        download_dir,
        store.items_by_status(conn, ["done"]),
        inspect,
        thumbnail_width,
        progress,
        should_continue,
        workers=workers,
    )
