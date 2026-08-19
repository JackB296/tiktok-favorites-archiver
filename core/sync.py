"""Sync orchestrator: concurrent, pausable/continue/stoppable, rate-limited.

Pulls pending/failed items from the store and processes each (resolve via Cobalt
→ download video or rebuild slideshow + save raw assets → update status), with a
bounded worker pool. The Cobalt rate limit lives inside the resolver
(``deps.resolve``); DB access is serialized by a lock so a single shared
connection is safe across workers while the slow I/O runs in parallel.

Only ``store`` + stdlib are imported at module load; the heavy deps (requests,
moviepy, PIL) are wired lazily in ``build_default_deps``, so this module and its
orchestration logic are unit-testable with a fake ``Deps``.
"""
import os
import logging
from collections import namedtuple

from core import (
    config, fallback_audio, indexer as archive_indexer, layout, media, runs, store,
)

# Injectable work backends (real ones wired in build_default_deps).
#
# ``audio_sources`` + ``fallback_fingerprints`` are what let a slideshow's
# soundtrack be fetched by more than one route and checked against the default
# tracks, so a substitution is recorded instead of archived as if it were real.
Deps = namedtuple(
    "Deps",
    "resolve download_file build_slideshow save_assets default_audio "
    "ytdlp_download inspect_media source_probe audio_sources fallback_fingerprints",
    defaults=(None, None, None, None, ()),
)


def _errstr(error):
    return None if error is None else str(error)


def _fact(facts, name, default=None):
    if facts is None:
        return default
    if isinstance(facts, dict):
        return facts.get(name, default)
    return getattr(facts, name, default)


def _audible(facts):
    return bool(_fact(facts, "has_audio", True)) and not bool(
        _fact(facts, "audio_silent", False)
    )


def _pixels(facts):
    return int(_fact(facts, "width", 0) or 0) * int(_fact(facts, "height", 0) or 0)


def _candidate_is_better(candidate, current):
    if current is None:
        return True
    if _audible(candidate) != _audible(current):
        return _audible(candidate)
    return _pixels(candidate) > _pixels(current)


def _inspect(deps, path):
    if deps.inspect_media is None:
        return None
    try:
        return deps.inspect_media(path)
    except Exception:
        return None


def _try_ytdlp_candidate(deps, link, out, current_facts=None):
    if deps.ytdlp_download is None:
        return False
    candidate = out + ".ytdlp-candidate.mp4"
    try:
        if not deps.ytdlp_download(link, candidate):
            return False
        candidate_facts = _inspect(deps, candidate)
        if deps.inspect_media is not None and candidate_facts is None:
            return False
        if _candidate_is_better(candidate_facts, current_facts):
            os.replace(candidate, out)
            return True
        return False
    finally:
        if os.path.exists(candidate):
            try:
                os.remove(candidate)
            except OSError:
                pass


def _source_offers_more_pixels(deps, link, current_facts):
    if deps.source_probe is None or current_facts is None:
        return False
    try:
        info = deps.source_probe(link, include_comments=False)
    except Exception:
        return False
    advertised = int(info.get("width") or 0) * int(info.get("height") or 0)
    return advertised > _pixels(current_facts)


def process_item(deps, download_dir, item):
    """Do the work for one item and return an outcome dict (no DB, no pool).

    Status mapping: success → done; transient/unknown → failed (retried next run);
    Cobalt 'error' (gone) → expired; non-photo picker → skipped.
    """
    n = item["id"]
    result = deps.resolve(item["link"])
    kind = result.kind

    if kind == "video":
        out = layout.movie(download_dir, n)
        if deps.download_file(result.url, out):
            current_facts = _inspect(deps, out)
            needs_audio_recovery = (
                current_facts is not None and not _audible(current_facts)
            )
            needs_quality_upgrade = _source_offers_more_pixels(
                deps, item["link"], current_facts,
            )
            used_ytdlp = (needs_audio_recovery or needs_quality_upgrade) and _try_ytdlp_candidate(
                deps, item["link"], out, current_facts,
            )
            return {
                "status": "done", "kind": "video", "has_assets": 0,
                "download_source": "yt-dlp" if used_ytdlp else "cobalt",
            }
        if _try_ytdlp_candidate(deps, item["link"], out):
            return {
                "status": "done", "kind": "video", "has_assets": 0,
                "download_source": "yt-dlp",
            }
        return {"status": "failed", "kind": "video", "error": "video download failed"}

    if kind == "slideshow":
        if not result.images:
            return {"status": "failed", "kind": "slideshow", "error": "no images in response"}

        def encode(images, audio, audio_source):
            out = layout.movie(download_dir, n)
            if deps.build_slideshow(images, audio, out):
                return {"status": "done", "kind": "slideshow", "has_assets": 1,
                        "audio_source": audio_source}
            return {"status": "failed", "kind": "slideshow", "has_assets": 1,
                    "audio_source": audio_source, "error": "encode failed"}

        outcome = media.recover_slideshow_assets(
            deps, download_dir, n, item["link"], result.images, result.audio, encode,
        )
        if outcome is None:
            return {"status": "failed", "kind": "slideshow", "error": "all images failed"}
        return outcome

    # A failed Cobalt resolve is not definitive. yt-dlp's selector requires a
    # real video+audio rendition, so a photo post's soundtrack cannot be
    # mistaken for a video here.
    out = layout.movie(download_dir, n)
    if _try_ytdlp_candidate(deps, item["link"], out):
        return {
            "status": "done", "kind": "video", "has_assets": 0,
            "download_source": "yt-dlp",
        }

    if kind == "error":       # Cobalt says the post is gone → don't retry
        return {"status": "expired", "kind": "unresolved", "error": _errstr(result.error)}
    if kind == "unsupported":  # picker without photos → not for us
        return {"status": "skipped", "kind": "unknown", "error": _errstr(result.error)}
    # transient / unknown → retryable
    return {"status": "failed", "kind": "unknown", "error": _errstr(result.error)}


def build_default_deps(limiter=None, default_audio=None, fallback_fingerprints=()):
    """Wire the real backends (lazy-imports the heavy deps)."""
    from core import cobalt, download, slideshow, assets, media_index, slideshow_audio, ytdlp_adapter
    if limiter is None:
        limiter = cobalt.RateLimiter(config.RATE_MAX_CALLS, config.RATE_PERIOD)
    return Deps(
        resolve=lambda link: cobalt.resolve(link, limiter=limiter),
        download_file=download.download_file,
        build_slideshow=slideshow.create_slideshow,
        save_assets=assets.save_assets,
        default_audio=default_audio or config.DEFAULT_AUDIO,
        ytdlp_download=ytdlp_adapter.download_best_video,
        inspect_media=media_index.inspect_media,
        source_probe=ytdlp_adapter.extract_post,
        audio_sources=slideshow_audio.build_sources(limiter=limiter),
        fallback_fingerprints=fallback_fingerprints,
    )


def _default_deps_for(conn, download_dir):
    """Build the real backends with the effective slideshow fallback audio."""
    name = store.get_library_settings(conn)["default_audio_name"]
    return build_default_deps(
        default_audio=media.resolve_default_audio(download_dir, name, config.DEFAULT_AUDIO),
        fallback_fingerprints=fallback_audio.known(download_dir, custom_name=name),
    )


def run_sync(conn, download_dir, deps=None, concurrency=None, progress=None,
             statuses=("pending", "failed"), wait=None,
             indexer=archive_indexer.index_pending_items, thumbnail_width=None,
             control=None):
    """Process all matching items. Honors run_state pause/continue/stop.

    Returns final counts-by-status. ``control`` is normally supplied by
    ``runs.execute``; direct callers (tests, CLI helpers) may instead pass
    ``progress``/``wait`` and a local control is built.
    """
    if deps is None:
        deps = _default_deps_for(conn, download_dir)
    if control is None:
        control = runs.RunControl(conn, progress=progress, wait=wait)

    os.makedirs(download_dir, exist_ok=True)

    with control.db_lock:
        store.reset_interrupted_downloads(conn)
        rs = store.get_run_state(conn)
        library = store.get_library_settings(conn)
        eff_concurrency = int(concurrency or (rs["concurrency"] if rs else config.CONCURRENCY) or config.CONCURRENCY)
        items = store.items_by_status(conn, list(statuses))

    def handle(item):
        if not control.should_continue():
            return
        with control.db_lock:
            store.set_status(conn, item["id"], "downloading")
        try:
            outcome = process_item(deps, download_dir, item)
        except Exception as error:
            logging.exception("Archive-media work failed for item %s", item["id"])
            outcome = {"status": "failed", "kind": "unknown", "error": _errstr(error)}
        with control.db_lock:
            store.record_work_outcome(conn, item["id"], outcome)
        control.progress({"id": item["id"], **outcome})

    runs.drive(items, eff_concurrency, control, handle)

    if indexer is not None and library["index_enabled"] and not control.stop_requested():
        # Phase-only write: entering the indexing phase must not overwrite a
        # concurrent pause or stop (stop_requested does not wait out a pause).
        control.set_phase("indexing")
        indexer(
            conn,
            download_dir,
            thumbnail_width=thumbnail_width or library["thumbnail_width"],
            progress=control.progress,
            should_continue=control.should_continue,
        )

    with control.db_lock:
        return store.counts_by_status(conn)


def run_index(conn, download_dir, progress=None, wait=None, indexer=archive_indexer.rebuild_index,
              control=None):
    """Rebuild the Gallery index as a controllable Archive run."""
    if control is None:
        control = runs.RunControl(conn, progress=progress, wait=wait)
    settings = store.get_library_settings(conn)
    return indexer(
        conn,
        download_dir,
        thumbnail_width=settings["thumbnail_width"],
        progress=control.progress,
        should_continue=control.should_continue,
    )


def backfill_item(deps, download_dir, item):
    """Re-resolve one item to recover raw slideshow assets (does not change status).

    Returns None for a transient failure (e.g. rate limited out of retries): the
    row is left untouched — including any kind learned on an earlier pass — so
    the item is retried on the next run.
    """
    result = deps.resolve(item["link"])
    kind = result.kind
    if kind == "video":
        return {"kind": "video", "has_assets": 0}
    if kind == "slideshow":
        outcome = media.recover_slideshow_assets(
            deps,
            download_dir,
            item["id"],
            item["link"],
            result.images,
            result.audio,
            lambda _images, _audio, audio_source: {
                "kind": "slideshow", "has_assets": 1, "audio_source": audio_source,
            },
        )
        if outcome is None:
            return {"kind": "slideshow", "has_assets": 0}
        return outcome
    if kind == "error":
        return {"kind": "unresolved", "has_assets": 0}
    if kind == "transient":
        return None
    return {"kind": "unknown", "has_assets": 0}


def items_needing_backfill(conn):
    """Downloaded items that still lack raw assets and aren't already known videos."""
    return [
        row for row in store.all_items(conn)
        if row["has_assets"] == 0 and row["kind"] != "video"
        and store.is_redownloadable(row) and row["status"] != "ignored"
    ]


def run_backfill(conn, download_dir, deps=None, concurrency=None, progress=None, wait=None,
                 control=None):
    """One-time pass: re-resolve past favorites and recover slideshow raw assets.

    Idempotent/resumable — videos get marked (and skipped next time), slideshows
    with recovered assets drop out of the selection.
    """
    if deps is None:
        deps = _default_deps_for(conn, download_dir)
    if control is None:
        control = runs.RunControl(conn, progress=progress, wait=wait)
    os.makedirs(download_dir, exist_ok=True)

    with control.db_lock:
        rs = store.get_run_state(conn)
        eff_concurrency = int(concurrency or (rs["concurrency"] if rs else config.CONCURRENCY) or config.CONCURRENCY)
        items = items_needing_backfill(conn)

    total = len(items)
    tally = {"completed": 0, "recovered": 0}
    control.progress({"event": "backfill", "completed": 0, "total": total, "recovered": 0})

    def handle(item):
        if not control.should_continue():
            return
        try:
            outcome = backfill_item(deps, download_dir, item)
        except Exception:
            # Leave the row untouched (a transient crash must not clobber a
            # learned kind); the item stays selected for the next run.
            logging.exception("Asset backfill failed for item %s", item["id"])
            outcome = None
        with control.db_lock:
            if outcome is not None:
                store.record_asset_recovery(conn, item["id"], outcome)
            tally["completed"] += 1
            if outcome and outcome.get("has_assets"):
                tally["recovered"] += 1
            event = {"event": "backfill", "id": item["id"],
                     "kind": outcome["kind"] if outcome else "transient",
                     "has_assets": outcome.get("has_assets", 0) if outcome else 0,
                     "completed": tally["completed"], "total": total,
                     "recovered": tally["recovered"]}
        control.progress(event)

    runs.drive(items, eff_concurrency, control, handle)

    with control.db_lock:
        return {"with_assets": sum(1 for r in store.all_items(conn) if r["has_assets"] == 1)}


def _cli(kind, description, runner, progress, done_message, argv):
    """Shared `python -m core <kind>` body: parse args, import, run one Archive run."""
    import argparse
    from core import cobalt, export, importer

    parser = argparse.ArgumentParser(prog=f"core {kind}", description=description)
    parser.add_argument("--cobalt-url", default=config.COBALT_API_URL)
    parser.add_argument("--data-file", default=config.VIDEO_LINKS_FILE)
    parser.add_argument("--download-dir", default=config.DOWNLOAD_DIR)
    parser.add_argument("--db", default=config.DB_FILE)
    parser.add_argument("--concurrency", type=int, default=config.CONCURRENCY)
    args = parser.parse_args(argv)

    config.COBALT_API_URL = args.cobalt_url
    config.DOWNLOAD_DIR = args.download_dir
    config.VIDEO_LINKS_FILE = args.data_file
    config.setup_logging()

    if not cobalt.check_cobalt(config.COBALT_API_URL):
        logging.error("Cobalt is unreachable — aborting. Start Cobalt or fix --cobalt-url.")
        return
    conn = store.init_db(store.connect(args.db))
    runs.recover(conn)  # a crash-stale 'paused' would otherwise block the run forever
    try:
        importer.import_all(conn, config.VIDEO_LINKS_FILE, config.DOWNLOAD_DIR)
    except export.ExportError as error:
        # A corrupt export must not block syncing what's already in the DB —
        # match the old lenient behavior, but say so loudly.
        logging.error(f"Skipping import — {config.VIDEO_LINKS_FILE} is not a usable export: {error}")

    result = runs.execute(
        conn,
        kind,
        runner,
        config.DOWNLOAD_DIR,
        concurrency=args.concurrency,
        progress=progress,
    )
    logging.info(done_message.format(result))


def run_cli(argv=None):
    """`python -m core sync` — import the export, then run the concurrent sync."""
    def progress(event):
        logging.info(f"[{event['id']}] {event['status']} ({event.get('kind')})")

    _cli("sync", "DB-driven concurrent TikTok favorites sync.",
         run_sync, progress, "Sync complete: {}", argv)


def run_backfill_cli(argv=None):
    """`python -m core backfill` — recover raw slideshow assets for past favorites."""
    def progress(event):
        if event.get("id") is None:
            logging.info(f"backfill: {event.get('total', 0)} favorites to check")
            return
        logging.info(f"[{event['id']}] backfill: kind={event.get('kind')} assets={event.get('has_assets')}")

    _cli("backfill", "Recover raw slideshow images+audio for already-downloaded favorites.",
         run_backfill, progress, "Backfill complete: {}", argv)
