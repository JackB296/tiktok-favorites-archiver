"""Resumable Gallery-index work for finished Archive media."""
import os

from core import media_index, store


def _fingerprint(path):
    stat = os.stat(path)
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def index_pending_items(conn, download_dir, inspect=media_index.index_media, thumbnail_width=480):
    """Index every finished Archive item that has no durable thumbnail yet."""
    result = {"indexed": 0, "failed": 0}
    for item in store.items_needing_index(conn):
        movie = os.path.join(download_dir, f"{item['id']}.mp4")
        if not os.path.isfile(movie):
            continue
        try:
            index = inspect(download_dir, item["id"], thumbnail_width)
            store.record_media_index(conn, item["id"], index._asdict(), _fingerprint(movie))
            result["indexed"] += 1
        except Exception as error:
            store.record_media_index_error(conn, item["id"], str(error))
            result["failed"] += 1
    return result
