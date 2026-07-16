"""Automatic song identification as a pausable Archive run.

Mirrors ``core/enrich.py``: walk the items that still need a song, rate-limited
and pausable/stoppable, persisting each outcome and emitting progress. For each
item it cuts a short audio clip (ffmpeg) and asks the identifier (Shazam) what
it is — a match is stored once per distinct track, a miss is remembered so
re-runs skip it, and a failure is kept retryable.

The identifier, clip source, and extractor are injected, so the whole loop is
unit-testable with fakes — no ffmpeg, no shazamio, no network.
"""
import logging
import os
import tempfile

from core import config, layout, media_index, runs, songid, store
from core.cobalt import RateLimiter


def _identify_one(download_dir, item_id, identifier, source, extractor):
    """Cut a temp clip for one item and identify it; SongMatch or None.

    The clip is always removed. Extraction/identification errors propagate so the
    caller can record them as a retryable failure.
    """
    src = source(download_dir, item_id)
    fd, clip = tempfile.mkstemp(prefix=f"songid-{item_id}-", suffix=".wav")
    os.close(fd)
    try:
        extractor(src, clip)
        return identifier(clip)
    finally:
        try:
            os.remove(clip)
        except OSError:
            pass


def identify_items(conn, download_dir, identifier=None, source=None, extractor=None,
                   limiter=None, progress=None, should_continue=None, retry_no_match=False):
    """Identify songs for items that need it. Returns the count newly identified."""
    identifier = identifier or songid.recognize
    source = source or layout.source_audio
    extractor = extractor or media_index.extract_clip
    if limiter is None:
        limiter = RateLimiter(config.SONG_ID_RATE_MAX_CALLS, config.SONG_ID_RATE_PERIOD)

    items = store.items_needing_identification(conn, retry_no_match=retry_no_match)
    identified = no_match = errors = 0
    total = len(items)
    if progress:
        progress({"event": "identification", "completed": 0, "total": total,
                  "identified": 0, "no_match": 0, "errors": 0})
    for completed, item in enumerate(items, start=1):
        if should_continue and not should_continue():
            break
        item_id = item["id"]
        limiter.acquire()
        title = None
        try:
            match = _identify_one(download_dir, item_id, identifier, source, extractor)
            if match:
                song_id = store.upsert_song(
                    conn, songid.dedup_key(match), match.title, artist=match.artist,
                    album=match.album, art_url=match.art_url, shazam_url=match.shazam_url,
                    apple_url=match.apple_url, spotify_url=match.spotify_url, shazam_key=match.key,
                )
                store.set_item_song(conn, item_id, song_id, source="auto")
                identified += 1
                title = match.title
            else:
                store.set_item_song_no_match(conn, item_id)
                no_match += 1
        except Exception as e:  # keep the run going; the item stays retryable
            logging.warning(f"song identification failed for item {item_id}: {e}")
            store.set_item_song_error(conn, item_id, str(e))
            errors += 1
        if progress:
            progress({"event": "identification", "id": item_id, "title": title,
                      "completed": completed, "total": total,
                      "identified": identified, "no_match": no_match, "errors": errors})
    return identified


def run_identification(conn, download_dir, progress=None, wait=None, identifier=None,
                       source=None, extractor=None, limiter=None, control=None):
    """Identify songs as a pausable Archive run (mirrors ``run_enrichment``)."""
    if control is None:
        control = runs.RunControl(conn, progress=progress, wait=wait)
    return identify_items(
        conn, download_dir, identifier=identifier, source=source, extractor=extractor,
        limiter=limiter, progress=control.progress, should_continue=control.should_continue,
    )
