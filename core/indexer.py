"""Resumable Gallery-index work for finished Archive media."""
import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from core import config, layout, media_index, store


def _default_workers():
    return max(1, config.INDEX_WORKERS)


def _index_items(conn, download_dir, items, inspect, thumbnail_width, progress, should_continue, workers=None):
    """Index a known set of finished items and report deterministic progress.

    The ffprobe/ffmpeg inspection runs on a bounded worker pool (a full rebuild
    is otherwise pinned to one core for tens of minutes); all database writes
    stay on the calling thread, batch by batch, so no connection is shared
    across threads. Pause/stop is honored between batches.
    """
    candidates = [
        item for item in items
        if os.path.isfile(layout.movie(download_dir, item["id"]))
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
            movie = layout.movie(download_dir, item["id"])
            store.record_media_index(conn, item["id"], index._asdict(), media_index.file_fingerprint(movie))
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
        accepting = not should_continue or should_continue()
        iterator = iter(candidates)
        pending = {}
        while accepting and len(pending) < workers:
            try:
                item = next(iterator)
            except StopIteration:
                accepting = False
                break
            pending[pool.submit(
                inspect, download_dir, item["id"], thumbnail_width,
            )] = item

        while pending:
            completed_futures, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed_futures:
                item = pending.pop(future)
                record(item, future.result)
                if not accepting:
                    continue
                if should_continue and not should_continue():
                    accepting = False
                    continue
                try:
                    next_item = next(iterator)
                except StopIteration:
                    accepting = False
                    continue
                pending[pool.submit(
                    inspect, download_dir, next_item["id"], thumbnail_width,
                )] = next_item
    return result


def index_pending_items(conn, download_dir, inspect=media_index.index_media, thumbnail_width=480, progress=None, should_continue=None, workers=None, item_ids=None):
    """Index finished Archive items without a durable thumbnail yet."""
    candidates = store.items_needing_index(conn)
    if item_ids is not None:
        wanted = {int(value) for value in item_ids}
        candidates = [item for item in candidates if item["id"] in wanted]
    return _index_items(
        conn,
        download_dir,
        candidates,
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
        store.items_for_index_rebuild(conn),
        inspect,
        thumbnail_width,
        progress,
        should_continue,
        workers=workers,
    )
