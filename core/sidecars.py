"""Plex/Kodi metadata sidecars for finished Archive media.

Writes ``<n>.nfo`` (title, author, date, source link) and a ``<n>.jpg`` poster
next to each finished ``<n>.mp4`` so media servers show real titles and artwork
instead of bare numbers. Strictly non-destructive: the archived media is never
modified. Posters convert the stored Gallery thumbnail when one exists,
otherwise they grab the first video frame; both go through ffmpeg, like the
Gallery indexer.
"""
import os
import time
import subprocess
from xml.sax.saxutils import escape

from core import store


_HALT = ("stopping", "stopped")
_TITLE_LIMIT = 120


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
    if item["favorited_at"]:
        lines.append(f"  <premiered>{escape(str(item['favorited_at'])[:10])}</premiered>")
    plot = _printable(" ".join(filter(None, [(item["caption"] or "").strip(), item["link"]])))
    if plot:
        lines.append(f"  <plot>{escape(plot)}</plot>")
    lines.append("</movie>")
    return "\n".join(lines) + "\n"


def make_poster(source, target, runner=subprocess.run):
    """Write one JPEG poster frame without changing the source media.

    The explicit muxer/codec flags let the target carry a temp suffix; the
    caller publishes it atomically.
    """
    runner(
        ["ffmpeg", "-y", "-i", source, "-frames:v", "1", "-q:v", "3", "-c:v", "mjpeg", "-f", "image2", target],
        check=True,
        capture_output=True,
        text=True,
    )


def write_sidecars(conn, download_dir, progress=None, should_continue=None, make_poster=make_poster):
    """Write NFO + poster sidecars for every finished local video.

    Idempotent and resumable: the NFO is always rewritten (cheap, and picks up
    enriched captions), the poster is skipped when it already exists.
    """
    candidates = [
        item for item in store.items_by_status(conn, ["done"])
        if os.path.isfile(os.path.join(download_dir, f"{item['id']}.mp4"))
    ]
    result = {"written": 0, "failed": 0}
    total = len(candidates)
    if progress:
        progress({"event": "sidecars", **result, "completed": 0, "total": total})
    for completed, item in enumerate(candidates, start=1):
        if should_continue and not should_continue():
            break
        try:
            _write_one(download_dir, item, make_poster)
            result["written"] += 1
        except Exception:
            result["failed"] += 1
        if progress:
            progress({"event": "sidecars", **result, "completed": completed, "total": total})
    return result


def _write_one(download_dir, item, make_poster):
    item_id = item["id"]
    xml = nfo_xml(item)  # build before opening so a failure leaves no temp file
    nfo_path = os.path.join(download_dir, f"{item_id}.nfo")
    tmp_path = nfo_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(xml)
    os.replace(tmp_path, nfo_path)

    poster_path = os.path.join(download_dir, f"{item_id}.jpg")
    if os.path.exists(poster_path):
        return
    thumbnail = item["thumbnail_path"] and os.path.join(download_dir, item["thumbnail_path"])
    source = thumbnail if thumbnail and os.path.isfile(thumbnail) else os.path.join(download_dir, f"{item_id}.mp4")
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


def run_sidecars(conn, download_dir, progress=None, wait=None):
    """Write metadata sidecars as a controllable Archive run."""
    if wait is None:
        wait = lambda: time.sleep(0.1)  # noqa: E731

    def state():
        return store.get_run_state(conn)["state"]

    def keep_going():
        while state() == "paused":
            wait()
        return state() not in _HALT

    return write_sidecars(conn, download_dir, progress=progress, should_continue=keep_going)
