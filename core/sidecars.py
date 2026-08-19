"""Plex/Kodi metadata sidecars for finished Archive media.

Writes ``<n>.nfo`` (title, author, date, source link) and a ``<n>.jpg`` poster
next to each finished ``<n>.mp4`` so media servers show real titles and artwork
instead of bare numbers. Strictly non-destructive: the archived media is never
modified. Posters convert the stored Gallery thumbnail when one exists,
otherwise they grab the first video frame; both go through ffmpeg, like the
Gallery indexer.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import os
from xml.sax.saxutils import escape

from core import config, layout, media_index, portable_metadata, runs, source_metadata, store


_TITLE_LIMIT = 120


def needs_work(conn, download_dir):
    if store.items_needing_source_metadata(conn):
        return True
    return any(
        item["status"] == "done"
        and os.path.isfile(layout.movie(download_dir, item["id"]))
        and not os.path.isfile(layout.nfo(download_dir, item["id"]))
        for item in store.all_items(conn)
    )


def _printable(text):
    """XML 1.0 forbids most control characters; strip them from TikTok text."""
    return "".join(ch for ch in text if ch == "\t" or ord(ch) >= 32)


def _title(item):
    caption = _printable(" ".join((item["caption"] or "").split()))
    if not caption:
        return f"Favorite {item['id']}"
    return caption if len(caption) <= _TITLE_LIMIT else caption[: _TITLE_LIMIT - 1] + "…"


def nfo_xml(item):
    """Kodi/Jellyfin-style movie NFO for one Archive item."""
    lines = ["<movie>", f"  <title>{escape(_title(item))}</title>"]
    if item["author"]:
        lines.append(f"  <studio>{escape(_printable(item['author']))}</studio>")
    premiered = item["source_posted_at"] or item["favorited_at"]
    if premiered:
        lines.append(f"  <premiered>{escape(str(premiered)[:10])}</premiered>")
    description = (item["description"] or item["caption"] or "").strip()
    plot = _printable(" ".join(filter(None, [description, item["link"]])))
    if plot:
        lines.append(f"  <plot>{escape(plot)}</plot>")
    lines.append("</movie>")
    return "\n".join(lines) + "\n"


def write_sidecars(conn, download_dir, progress=None, should_continue=None,
                   make_poster=media_index.make_poster, workers=None):
    """Write NFO + poster sidecars for every finished local video.

    Idempotent and resumable: the NFO is always rewritten (cheap, and picks up
    enriched captions), the poster is skipped when it already exists.
    """
    candidates = [
        item for item in store.items_by_status(conn, ["done"])
        if os.path.isfile(layout.movie(download_dir, item["id"]))
    ]
    result = {"written": 0, "failed": 0}
    total = len(candidates)
    workers = max(1, int(workers or config.SIDECAR_WORKERS))
    completed = 0
    if progress:
        progress({"event": "sidecars", **result, "completed": 0, "total": total})

    def record(outcome):
        nonlocal completed
        try:
            outcome()
            result["written"] += 1
        except Exception:
            result["failed"] += 1
        completed += 1
        if progress:
            progress({"event": "sidecars", **result, "completed": completed, "total": total})

    if workers == 1:
        for item in candidates:
            if should_continue and not should_continue():
                break
            record(lambda item=item: _write_one(download_dir, item, make_poster))
        return result

    iterator = iter(candidates)
    accepting = True
    pending = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while accepting and len(pending) < workers:
            if should_continue and not should_continue():
                accepting = False
                break
            try:
                item = next(iterator)
            except StopIteration:
                accepting = False
                break
            pending[pool.submit(_write_one, download_dir, item, make_poster)] = item
        while pending:
            completed_futures, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed_futures:
                pending.pop(future)
                record(future.result)
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
                    _write_one, download_dir, next_item, make_poster,
                )] = next_item
    return result


def _write_one(download_dir, item, make_poster):
    item_id = item["id"]
    xml = nfo_xml(item)  # build before opening so a failure leaves no temp file
    nfo_path = layout.nfo(download_dir, item_id)
    tmp_path = nfo_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(xml)
    os.replace(tmp_path, nfo_path)

    poster_path = layout.poster(download_dir, item_id)
    if os.path.exists(poster_path):
        return
    relative_thumbnail = item["thumbnail_path"] or item["source_thumbnail_path"]
    thumbnail = relative_thumbnail and os.path.join(download_dir, relative_thumbnail)
    source = thumbnail if thumbnail and os.path.isfile(thumbnail) else layout.movie(download_dir, item_id)
    poster_tmp = poster_path + ".tmp"
    try:
        make_poster(source, poster_tmp)
        os.replace(poster_tmp, poster_path)
    finally:
        if os.path.exists(poster_tmp):
            try:
                os.remove(poster_tmp)
            except OSError:
                pass


def run_sidecars(conn, download_dir, progress=None, wait=None, control=None,
                 extractor=None, fetch=source_metadata.fetch_resource,
                 make_poster=media_index.make_poster, recheck=False,
                 embed=portable_metadata.embed_library):
    """Backfill rich source files, then write media-server sidecars."""
    if control is None:
        control = runs.RunControl(conn, progress=progress, wait=wait)
    source_result = source_metadata.backfill(
        conn, download_dir, extractor=extractor, fetch=fetch,
        progress=control.progress, should_continue=control.should_continue,
        recheck=recheck,
    )
    media_result = write_sidecars(
        conn, download_dir, progress=control.progress,
        should_continue=control.should_continue, make_poster=make_poster,
    )
    portable_enabled = bool(store.get_library_settings(conn)["portable_metadata_enabled"])
    portable_result = {"enabled": portable_enabled, "embedded": 0, "skipped": 0, "failed": 0}
    if portable_enabled:
        portable_result.update(embed(
            conn, download_dir, progress=control.progress,
            should_continue=control.should_continue,
        ))
    return {
        "source_metadata": source_result, "media_server": media_result,
        "portable_media": portable_result,
    }
