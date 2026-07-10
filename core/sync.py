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
import time
import logging
import threading
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

from core import config, indexer as archive_indexer, media, runs, store

# Injectable work backends (real ones wired in build_default_deps).
Deps = namedtuple("Deps", "resolve download_file build_slideshow save_assets default_audio")

# run_state values that mean "stop pulling new work".
_HALT = ("stopping", "stopped")


def _errstr(error):
    return None if error is None else str(error)


def _drive(items, concurrency, state, wait, handle):
    """Run ``handle(item)`` over ``items`` with a bounded pool, honoring pause/stop.

    ``state()`` returns the current run_state; ``wait()`` is the pause poll;
    ``handle(item)`` does the per-item work and its own DB writes. Shared by the
    sync and backfill orchestrators so the pause/stop logic lives in one place.
    """
    if concurrency <= 1:
        for item in items:
            if state() in _HALT:
                break
            handle(item)
        return
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = []
        for item in items:
            if state() in _HALT:
                break
            while state() == "paused":
                wait()
            if state() in _HALT:
                break
            futures.append(pool.submit(handle, item))
        for f in futures:
            f.result()


def process_item(deps, download_dir, item):
    """Do the work for one item and return an outcome dict (no DB, no pool).

    Status mapping: success → done; transient/unknown → failed (retried next run);
    Cobalt 'error' (gone) → expired; non-photo picker → skipped.
    """
    n = item["id"]
    result = deps.resolve(item["link"])
    kind = result.kind

    if kind == "video":
        out = os.path.join(download_dir, f"{n}.mp4")
        if deps.download_file(result.url, out):
            return {"status": "done", "kind": "video", "has_assets": 0}
        return {"status": "failed", "kind": "video", "error": "video download failed"}

    if kind == "slideshow":
        if not result.images:
            return {"status": "failed", "kind": "slideshow", "error": "no images in response"}

        def encode(images, audio):
            out = os.path.join(download_dir, f"{n}.mp4")
            if deps.build_slideshow(images, audio, out):
                return {"status": "done", "kind": "slideshow", "has_assets": 1}
            return {"status": "failed", "kind": "slideshow", "has_assets": 1, "error": "encode failed"}

        outcome = media.recover_slideshow_assets(deps, download_dir, n, result, encode)
        if outcome is None:
            return {"status": "failed", "kind": "slideshow", "error": "all images failed"}
        return outcome

    if kind == "error":       # Cobalt says the post is gone → don't retry
        return {"status": "expired", "kind": "unresolved", "error": _errstr(result.error)}
    if kind == "unsupported":  # picker without photos → not for us
        return {"status": "skipped", "kind": "unknown", "error": _errstr(result.error)}
    # transient / unknown → retryable
    return {"status": "failed", "kind": "unknown", "error": _errstr(result.error)}


def build_default_deps(limiter=None):
    """Wire the real backends (lazy-imports the heavy deps)."""
    from core import cobalt, download, slideshow, assets
    if limiter is None:
        limiter = cobalt.RateLimiter(config.RATE_MAX_CALLS, config.RATE_PERIOD)
    return Deps(
        resolve=lambda link: cobalt.resolve(link, limiter=limiter),
        download_file=download.download_file,
        build_slideshow=slideshow.create_slideshow,
        save_assets=assets.save_assets,
        default_audio=config.DEFAULT_AUDIO,
    )


def run_sync(conn, download_dir, deps=None, concurrency=None, progress=None,
             statuses=("pending", "failed"), wait=None,
             indexer=archive_indexer.index_pending_items, thumbnail_width=None):
    """Process all matching items. Honors run_state pause/continue/stop.

    Returns final counts-by-status. ``wait`` is the pause poll (injectable for tests).
    """
    if deps is None:
        deps = build_default_deps()
    if wait is None:
        wait = lambda: time.sleep(0.1)  # noqa: E731

    os.makedirs(download_dir, exist_ok=True)
    db_lock = threading.Lock()

    def state():
        with db_lock:
            return store.get_run_state(conn)["state"]

    with db_lock:
        rs = store.get_run_state(conn)
        library = store.get_library_settings(conn)
        eff_concurrency = int(concurrency or (rs["concurrency"] if rs else config.CONCURRENCY) or config.CONCURRENCY)
        items = store.items_by_status(conn, list(statuses))

    def handle(item):
        while state() == "paused":
            wait()
        if state() in _HALT:
            return
        with db_lock:
            store.set_status(conn, item["id"], "downloading")
        try:
            outcome = process_item(deps, download_dir, item)
        except Exception as error:
            logging.exception("Archive-media work failed for item %s", item["id"])
            outcome = {"status": "failed", "kind": "unknown", "error": _errstr(error)}
        with db_lock:
            store.record_work_outcome(conn, item["id"], outcome)
        if progress:
            progress({"id": item["id"], **outcome})

    _drive(items, eff_concurrency, state, wait, handle)

    if indexer is not None and library["index_enabled"] and state() not in _HALT:
        with db_lock:
            store.set_run_state(conn, state="running", phase="indexing")

        def continue_indexing():
            while state() == "paused":
                wait()
            return state() not in _HALT

        indexer(
            conn,
            download_dir,
            thumbnail_width=thumbnail_width or library["thumbnail_width"],
            progress=progress,
            should_continue=continue_indexing,
        )

    with db_lock:
        return store.counts_by_status(conn)


def run_index(conn, download_dir, progress=None, wait=None, indexer=archive_indexer.rebuild_index):
    """Rebuild the Gallery index as a controllable Archive job."""
    if wait is None:
        wait = lambda: time.sleep(0.1)  # noqa: E731

    def state():
        return store.get_run_state(conn)["state"]

    def continue_indexing():
        while state() == "paused":
            wait()
        return state() not in _HALT

    settings = store.get_library_settings(conn)
    return indexer(
        conn,
        download_dir,
        thumbnail_width=settings["thumbnail_width"],
        progress=progress,
        should_continue=continue_indexing,
    )


def backfill_item(deps, download_dir, item):
    """Re-resolve one item to recover raw slideshow assets (does not change status)."""
    result = deps.resolve(item["link"])
    kind = result.kind
    if kind == "video":
        return {"kind": "video", "has_assets": 0}
    if kind == "slideshow":
        outcome = media.recover_slideshow_assets(
            deps,
            download_dir,
            item["id"],
            result,
            lambda _images, _audio: {"kind": "slideshow", "has_assets": 1},
        )
        if outcome is None:
            return {"kind": "slideshow", "has_assets": 0}
        return outcome
    if kind == "error":
        return {"kind": "unresolved", "has_assets": 0}
    return {"kind": "unknown", "has_assets": 0}


def items_needing_backfill(conn):
    """Downloaded items that still lack raw assets and aren't already known videos."""
    return [
        row for row in store.all_items(conn)
        if row["has_assets"] == 0 and row["kind"] != "video"
        and not str(row["link"]).startswith("local://")
    ]


def run_backfill(conn, download_dir, deps=None, concurrency=None, progress=None, wait=None):
    """One-time pass: re-resolve past favorites and recover slideshow raw assets.

    Idempotent/resumable — videos get marked (and skipped next time), slideshows
    with recovered assets drop out of the selection.
    """
    if deps is None:
        deps = build_default_deps()
    if wait is None:
        wait = lambda: time.sleep(0.1)  # noqa: E731
    os.makedirs(download_dir, exist_ok=True)
    db_lock = threading.Lock()

    def state():
        with db_lock:
            return store.get_run_state(conn)["state"]

    with db_lock:
        rs = store.get_run_state(conn)
        eff_concurrency = int(concurrency or (rs["concurrency"] if rs else config.CONCURRENCY) or config.CONCURRENCY)
        items = items_needing_backfill(conn)

    def handle(item):
        while state() == "paused":
            wait()
        if state() in _HALT:
            return
        outcome = backfill_item(deps, download_dir, item)
        with db_lock:
            store.record_asset_recovery(conn, item["id"], outcome)
        if progress:
            progress({"id": item["id"], **outcome})

    _drive(items, eff_concurrency, state, wait, handle)

    with db_lock:
        return {"with_assets": sum(1 for r in store.all_items(conn) if r["has_assets"] == 1)}


def run_cli(argv=None):
    """`python -m core sync` — import the export, then run the concurrent sync."""
    import argparse
    from core import cobalt, importer

    parser = argparse.ArgumentParser(prog="core sync",
                                     description="DB-driven concurrent TikTok favorites sync.")
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
    importer.import_all(conn, config.VIDEO_LINKS_FILE, config.DOWNLOAD_DIR)

    def progress(event):
        logging.info(f"[{event['id']}] {event['status']} ({event.get('kind')})")

    counts = runs.execute(
        conn,
        "sync",
        run_sync,
        config.DOWNLOAD_DIR,
        concurrency=args.concurrency,
        progress=progress,
    )
    logging.info(f"Sync complete: {counts}")


def run_backfill_cli(argv=None):
    """`python -m core backfill` — recover raw slideshow assets for past favorites."""
    import argparse
    from core import cobalt, importer

    parser = argparse.ArgumentParser(
        prog="core backfill",
        description="Recover raw slideshow images+audio for already-downloaded favorites.",
    )
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
        logging.error("Cobalt is unreachable — aborting.")
        return
    conn = store.init_db(store.connect(args.db))
    importer.import_all(conn, config.VIDEO_LINKS_FILE, config.DOWNLOAD_DIR)

    def progress(event):
        logging.info(f"[{event['id']}] backfill: kind={event.get('kind')} assets={event.get('has_assets')}")

    result = runs.execute(
        conn,
        "backfill",
        run_backfill,
        config.DOWNLOAD_DIR,
        concurrency=args.concurrency,
        progress=progress,
    )
    logging.info(f"Backfill complete: {result}")
