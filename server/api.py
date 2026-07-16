"""FastAPI routes.

Thin wiring over the tested core/server logic, exercised end-to-end by
``tests/test_api_http.py`` (TestClient + fake runners; skipped where FastAPI
isn't installed). Each request opens its own SQLite connection (safe under
WAL + busy_timeout).
"""
import os
import json
import sqlite3
import tempfile
from queue import Empty

import anyio
from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse

from core import config, store, importer, cobalt, curation, export, layout, verify, inventory, legacy_bootstrap, manual_media, media_index, songid
from server import archive_items
from server.archive_items import ArchiveItems
from server.jobs import JobBusyError

router = APIRouter(prefix="/api")

HOWTO = """How to get your TikTok data export:

1. In the TikTok app or website: Settings and privacy -> Account -> Download your data.
2. Choose "All data" and the "JSON" format, then submit the request.
3. Wait for TikTok to prepare it (minutes to hours), reload, and download the archive.
4. Unzip it and upload the file named `user_data_tiktok.json` here.
"""


def _open(request: Request):
    return store.connect(request.app.state.db_path)


def _download_dir(request: Request):
    return request.app.state.download_dir


def _archive_items(request: Request, conn):
    return ArchiveItems(conn, _download_dir(request))


def _library_settings(conn):
    row = store.get_library_settings(conn)
    return {
        "index_enabled": row["index_enabled"],
        "thumbnail_width": row["thumbnail_width"],
        "song_id_enabled": row["song_id_enabled"],
        "default_audio_name": row["default_audio_name"],
        "index": store.library_index_status(conn),
    }


async def _json_body(request: Request):
    """Parse the JSON request body; malformed JSON is a 400, not a 500."""
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="request body must be valid JSON")


async def _exclusive(request: Request, operation):
    """Run exclusive maintenance (may take minutes, e.g. imports) on a worker thread.

    ``run_when_idle`` guards against a concurrent Archive-run start; the worker
    thread keeps blocking work (library scans, file installs, imports) off the
    event loop so ``/api/status`` and the SSE stream stay live meanwhile.
    ``JobBusyError`` propagates for the caller's 409 mapping.
    """
    return await anyio.to_thread.run_sync(
        lambda: request.app.state.jobs.run_when_idle(operation)
    )


@router.get("/health")
def health():
    return {"status": "ok", "cobalt_reachable": cobalt.check_cobalt(config.COBALT_API_URL)}


@router.get("/howto", response_class=PlainTextResponse)
def howto():
    return HOWTO


@router.get("/suggest")
def suggest(request: Request, q: str = ""):
    conn = _open(request)
    try:
        return store.suggest(conn, q)
    finally:
        conn.close()


def _register_saved_list_routes(resource, kind, display_noun):
    """GET/POST/DELETE for one saved named-list collection.

    All four collections (Gallery presets, term lists, playback queues, song
    playlists) share this implementation; per-collection validation lives in
    ``archive_items.SAVED_LIST_RESOURCES``.
    """

    @router.get(f"/{resource}")
    def list_entries(request: Request):
        conn = _open(request)
        try:
            return store.list_saved_lists(conn, kind)
        finally:
            conn.close()

    @router.post(f"/{resource}")
    async def create_entry(request: Request):
        try:
            name, payload = archive_items.parse_saved_list(resource, await _json_body(request))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        def write():
            conn = _open(request)
            try:
                entry_id = store.save_saved_list(conn, kind, name, payload)
                return {"id": entry_id, "name": name, **payload}
            finally:
                conn.close()

        try:
            return await anyio.to_thread.run_sync(write)
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail=f"a {display_noun} with that name already exists")

    @router.delete(f"/{resource}/{{entry_id}}")
    def delete_entry(request: Request, entry_id: int):
        conn = _open(request)
        try:
            if not store.delete_saved_list(conn, kind, entry_id):
                raise HTTPException(status_code=404, detail=f"{display_noun} not found")
            return {"ok": True}
        finally:
            conn.close()


for _resource, (_kind, _body_noun, _display_noun, _parse) in archive_items.SAVED_LIST_RESOURCES.items():
    _register_saved_list_routes(_resource, _kind, _display_noun)


@router.get("/songs")
def list_songs(request: Request):
    """Every identified song with its favorite count and ids, for the Music view."""
    conn = _open(request)
    try:
        return {"songs": store.distinct_songs(conn)}
    finally:
        conn.close()


@router.get("/items/page")
def page_items(request: Request):
    try:
        query = archive_items.parse_page_query(request.query_params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    conn = _open(request)
    try:
        try:
            return _archive_items(request, conn).page(**query)
        except ValueError as e:  # stale cursor, etc. — was a 500 before
            raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.get("/items/ids")
def item_ids(request: Request):
    conn = _open(request)
    try:
        return store.playable_item_ids(conn)
    finally:
        conn.close()


@router.get("/feed/ids")
def feed_ids(request: Request):
    """Ordered ids for every favorite matching a Gallery filter, so the Feed can
    play through exactly that filtered set. Same query vocabulary as /items/page."""
    try:
        query = archive_items.parse_page_query(request.query_params)
        # Same policy as mark-by-filter: paging keys don't belong in a
        # whole-set query (this endpoint returns every matching id at once).
        for key in ("limit", "cursor", "feed"):
            if key in query:
                raise ValueError(f"{key} is not a filter")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    conn = _open(request)
    try:
        return store.feed_ids(conn, **query)
    finally:
        conn.close()


@router.post("/items/selection")
async def item_selection(request: Request):
    body = await _json_body(request)
    item_ids = body.get("ids", []) if isinstance(body, dict) else None
    if (
        not isinstance(item_ids, list)
        or len(item_ids) > 100
        or any(type(item_id) is not int or item_id < 1 for item_id in item_ids)
    ):
        raise HTTPException(status_code=400, detail="ids must contain at most 100 positive integer item IDs")

    def project():
        # The projection walks the archive dir; keep it off the event loop
        # (the Feed calls this repeatedly while scrolling).
        conn = _open(request)
        try:
            return _archive_items(request, conn).selected(item_ids)
        finally:
            conn.close()

    return await anyio.to_thread.run_sync(project)


@router.post("/items/requeue")
async def requeue_items(request: Request):
    """Queue selected failed/missing favorites without disturbing healthy media."""
    body = await _json_body(request)
    item_ids = body.get("ids") if isinstance(body, dict) else None
    if (
        not isinstance(item_ids, list)
        or not 1 <= len(item_ids) <= 100
        or any(type(item_id) is not int or item_id < 1 for item_id in item_ids)
    ):
        raise HTTPException(status_code=400, detail="ids must contain 1 to 100 positive integer item IDs")
    def operation():
        conn = _open(request)
        try:
            return curation.requeue_selected(conn, _download_dir(request), item_ids)
        finally:
            conn.close()

    try:
        return await _exclusive(request, operation)
    except JobBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.post("/items/mark")
async def mark_items(request: Request):
    """Bulk offload/ignore marking by explicit ids, id range, or Gallery filter."""
    body = await _json_body(request)
    try:
        action, kind, value, dry_run = archive_items.parse_mark_request(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    def operation():
        conn = _open(request)
        try:
            return curation.mark(conn, _download_dir(request), action, kind, value, dry_run=dry_run)
        finally:
            conn.close()

    try:
        return await _exclusive(request, operation)
    except JobBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.get("/items/offload-suggestion")
def items_offload_suggestion(request: Request):
    conn = _open(request)
    try:
        return verify.offload_suggestion(conn, _download_dir(request))
    finally:
        conn.close()


@router.get("/items/{n}/window")
def item_window(request: Request, n: int, limit: int = 50):
    conn = _open(request)
    try:
        return _archive_items(request, conn).window(n, limit)
    finally:
        conn.close()


MAX_IMPORT_BYTES = 512 * 1024 * 1024  # far above any real TikTok export
MAX_REPLACEMENT_VIDEO_BYTES = 1024 * 1024 * 1024
MAX_REPLACEMENT_THUMBNAIL_BYTES = 20 * 1024 * 1024
MAX_DEFAULT_AUDIO_BYTES = 20 * 1024 * 1024


async def _stage_upload(upload, prefix, suffix, max_bytes=MAX_IMPORT_BYTES, directory=None):
    """Stream one multipart file to a unique temporary path."""
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=directory)
    try:
        received = 0
        with os.fdopen(fd, "wb") as f:
            while chunk := await upload.read(1024 * 1024):
                received += len(chunk)
                if received > max_bytes:
                    raise HTTPException(status_code=413, detail=f"{upload.filename or 'upload'} is too large")
                await anyio.to_thread.run_sync(f.write, chunk)
        return path
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


def _remove_temp_files(paths):
    for path in paths:
        try:
            os.unlink(path)
        except OSError:
            pass


@router.post("/items/{n}/media")
async def replace_item_media(
    request: Request,
    n: int,
    video: UploadFile = File(None),
    thumbnail: UploadFile = File(None),
):
    """Replace one Favorite's local MP4 and/or custom Gallery thumbnail."""
    if video is None and thumbnail is None:
        raise HTTPException(status_code=400, detail="choose a replacement video or thumbnail")
    upload_dir = layout.uploads_dir(_download_dir(request))
    staged_video = None
    staged_thumbnail = None
    try:
        if video is not None:
            staged_video = await _stage_upload(
                video,
                f".{n}-video-",
                ".upload",
                max_bytes=MAX_REPLACEMENT_VIDEO_BYTES,
                directory=upload_dir,
            )
        if thumbnail is not None:
            staged_thumbnail = await _stage_upload(
                thumbnail,
                f".{n}-thumbnail-",
                ".upload",
                max_bytes=MAX_REPLACEMENT_THUMBNAIL_BYTES,
                directory=upload_dir,
            )

        def operation():
            conn = _open(request)
            try:
                if store.get_item(conn, n) is None:
                    raise HTTPException(status_code=404, detail="item not found")
                manual_media.replace_item_media(
                    conn,
                    _download_dir(request),
                    n,
                    staged_video=staged_video,
                    staged_thumbnail=staged_thumbnail,
                )
                return _archive_items(request, conn).get(n)
            finally:
                conn.close()

        return await _exclusive(request, operation)
    except JobBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except manual_media.MediaReplacementError as error:
        raise HTTPException(status_code=400, detail=str(error))
    finally:
        _remove_temp_files([path for path in (staged_video, staged_thumbnail) if path])


@router.get("/songs/search")
def search_songs(request: Request, q: str = ""):
    """Search Apple's public catalog by text for the manual 'match it myself' flow.

    Gated on the opt-in setting to keep the whole song feature behind one switch;
    only the typed query leaves the machine (never any audio).
    """
    query = q.strip()
    if not query:
        return {"results": []}
    conn = _open(request)
    try:
        if not store.get_library_settings(conn)["song_id_enabled"]:
            raise HTTPException(status_code=409, detail="enable song identification in settings first")
    finally:
        conn.close()
    try:
        matches = songid.search(query, limit=8)
    except Exception as error:  # network failure / unexpected response
        raise HTTPException(status_code=502, detail=f"song search failed: {error}")
    return {"results": [dict(match._asdict()) for match in matches]}


@router.post("/items/{n}/song")
async def set_item_song(request: Request, n: int):
    """Attach a hand-picked song to a Favorite (manual identification)."""
    try:
        fields = archive_items.parse_song_match(await _json_body(request))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    match = songid.SongMatch(**fields)

    def operation():
        conn = _open(request)
        try:
            if store.get_item(conn, n) is None:
                raise HTTPException(status_code=404, detail="item not found")
            song_id = store.upsert_song(
                conn, songid.dedup_key(match), match.title, artist=match.artist,
                album=match.album, art_url=match.art_url, shazam_url=match.shazam_url,
                apple_url=match.apple_url, spotify_url=match.spotify_url, shazam_key=match.key,
            )
            store.set_item_song(conn, n, song_id, source="manual")
            return _archive_items(request, conn).get(n)
        finally:
            conn.close()

    try:
        return await _exclusive(request, operation)
    except JobBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))


def _legacy_mapping_segments(value):
    if not value:
        return None
    if not isinstance(value, str):
        raise legacy_bootstrap.LegacyBootstrapError("Mapping segments must be JSON text.")
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise legacy_bootstrap.LegacyBootstrapError("Mapping segments are not valid JSON.") from exc


@router.post("/import")
async def import_export(request: Request, file: UploadFile = File(...)):
    tmp_path = None
    try:
        tmp_path = await _stage_upload(file, "tiktok-export-", ".json")

        def operation():
            conn = _open(request)
            try:
                return importer.import_all(conn, tmp_path, _download_dir(request))
            finally:
                conn.close()

        return await _exclusive(request, operation)
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except HTTPException:
        raise
    except export.ExportError as exc:
        # The export module's typed error for unusable uploads (invalid JSON,
        # wrong shape); unexpected failures (disk, DB) stay 500s.
        raise HTTPException(status_code=400, detail=f"Invalid export: {exc}")
    finally:
        if tmp_path:
            _remove_temp_files([tmp_path])


async def _run_legacy_bootstrap(
    request,
    old_export,
    current_export,
    checkpoint,
    mapping_segments,
    operation,
    empty_library_conflict=False,
):
    """Stage the three legacy uploads, run `operation(plan)` when idle, clean up.

    `operation` receives a zero-arg callable that builds the bootstrap plan from
    the staged uploads. `empty_library_conflict` maps the "empty library"
    LegacyBootstrapError to 409 instead of 400.
    """
    paths = []
    try:
        paths.append(await _stage_upload(old_export, "tiktok-old-export-", ".json"))
        paths.append(await _stage_upload(current_export, "tiktok-current-export-", ".json"))
        paths.append(await _stage_upload(checkpoint, "tiktok-checkpoint-", ".txt"))
        segments = _legacy_mapping_segments(mapping_segments)

        def plan():
            return legacy_bootstrap.plan_bootstrap(
                paths[0], paths[1], paths[2], _download_dir(request),
                mapping_segments=segments,
            )

        return await _exclusive(request, lambda: operation(plan))
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except legacy_bootstrap.LegacyBootstrapError as exc:
        conflict = empty_library_conflict and "empty library" in str(exc)
        raise HTTPException(status_code=409 if conflict else 400, detail=str(exc))
    finally:
        _remove_temp_files(paths)


@router.post("/import/legacy-preview")
async def legacy_import_preview(
    request: Request,
    old_export: UploadFile = File(...),
    current_export: UploadFile = File(...),
    checkpoint: UploadFile = File(...),
    mapping_segments: str = Form(""),
):
    def operation(plan):
        conn = _open(request)
        try:
            if store.has_items(conn):
                raise legacy_bootstrap.LegacyBootstrapError(
                    "Legacy bootstrap requires an empty library database."
                )
        finally:
            conn.close()
        return plan().preview()

    return await _run_legacy_bootstrap(
        request, old_export, current_export, checkpoint, mapping_segments, operation
    )


@router.post("/import/legacy-apply")
async def legacy_import_apply(
    request: Request,
    old_export: UploadFile = File(...),
    current_export: UploadFile = File(...),
    checkpoint: UploadFile = File(...),
    preview_token: str = Form(...),
    confirmation: str = Form(...),
    mapping_segments: str = Form(""),
):
    if confirmation != "MIGRATE":
        raise HTTPException(status_code=400, detail="Type MIGRATE to confirm legacy bootstrap.")

    def operation(plan):
        built = plan()
        conn = _open(request)
        try:
            return legacy_bootstrap.apply_bootstrap(conn, built, preview_token)
        finally:
            conn.close()

    return await _run_legacy_bootstrap(
        request, old_export, current_export, checkpoint, mapping_segments, operation,
        empty_library_conflict=True,
    )


@router.get("/status")
def status(request: Request):
    return request.app.state.jobs.status()


@router.get("/run-history")
def run_history(request: Request, limit: int = 20):
    conn = _open(request)
    try:
        return store.list_run_history(conn, limit)
    finally:
        conn.close()


@router.get("/verify")
def verify_archive(request: Request):
    conn = _open(request)
    try:
        return verify.verify_archive(conn, _download_dir(request))
    finally:
        conn.close()


@router.post("/verify/requeue")
def requeue_missing(request: Request):
    def operation():
        conn = _open(request)
        try:
            return verify.requeue_missing(conn, _download_dir(request))
        finally:
            conn.close()

    try:
        return request.app.state.jobs.run_when_idle(operation)
    except JobBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.get("/library-settings")
def library_settings(request: Request):
    conn = _open(request)
    try:
        return _library_settings(conn)
    finally:
        conn.close()


@router.get("/library-stats")
def library_stats(request: Request):
    conn = _open(request)
    try:
        return store.library_statistics(conn)
    finally:
        conn.close()


@router.get("/archive-inventory.csv")
def archive_inventory(request: Request):
    """Download the compact database inventory; media files stay on disk."""
    def stream():
        conn = _open(request)
        try:
            yield from inventory.csv_lines(store.all_items(conn))
        finally:
            conn.close()

    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=archive-inventory.csv"},
    )


@router.put("/library-settings")
async def update_library_settings(request: Request):
    body = await _json_body(request)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="settings must be an object")

    def write():
        # Off the event loop: a contended SQLite write waits busy_timeout (5s).
        conn = _open(request)
        try:
            store.set_library_settings(
                conn,
                index_enabled=body.get("index_enabled"),
                thumbnail_width=body.get("thumbnail_width"),
                song_id_enabled=body.get("song_id_enabled"),
            )
            return _library_settings(conn)
        finally:
            conn.close()

    try:
        return await anyio.to_thread.run_sync(write)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/default-audio")
async def upload_default_audio(request: Request, audio: UploadFile = File(...)):
    """Set a custom slideshow fallback track, used when a photo post's original
    sound is gone. Applies to future encodes; existing MP4s keep their audio."""
    name = (audio.filename or "").strip() or "default-audio.mp3"
    if not name.lower().endswith(".mp3"):
        raise HTTPException(status_code=400, detail="upload an .mp3 file")
    download_dir = _download_dir(request)
    target = layout.custom_default_audio(download_dir)
    staged = None
    try:
        staged = await _stage_upload(
            audio, ".default-audio-", ".upload",
            max_bytes=MAX_DEFAULT_AUDIO_BYTES,
            directory=layout.uploads_dir(download_dir),
        )
        def install():
            # Blocking probe + file install + DB write — runs on a worker
            # thread so the event loop stays responsive.
            if not media_index.has_audio_stream(staged):
                raise HTTPException(status_code=400, detail="that file has no readable audio")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(staged, target)
            conn = _open(request)
            try:
                store.set_default_audio(conn, name)
                return _library_settings(conn)
            finally:
                conn.close()

        settings = await anyio.to_thread.run_sync(install)
        staged = None
        return settings
    finally:
        if staged:
            _remove_temp_files([staged])


@router.delete("/default-audio")
def clear_default_audio(request: Request):
    """Revert to the bundled default track and remove the uploaded custom one."""
    target = layout.custom_default_audio(_download_dir(request))
    try:
        os.remove(target)
    except OSError:
        pass
    conn = _open(request)
    try:
        store.set_default_audio(conn, None)
        return _library_settings(conn)
    finally:
        conn.close()


@router.get("/sync-settings")
def sync_settings(request: Request):
    conn = _open(request)
    try:
        return {"concurrency": store.get_run_state(conn)["concurrency"]}
    finally:
        conn.close()


@router.put("/sync-settings")
async def update_sync_settings(request: Request):
    body = await _json_body(request)
    concurrency = body.get("concurrency") if isinstance(body, dict) else None
    if type(concurrency) is not int or not 1 <= concurrency <= 16:
        raise HTTPException(status_code=400, detail="concurrency must be an integer from 1 to 16")

    def write():
        conn = _open(request)
        try:
            store.set_run_state(conn, concurrency=concurrency)
            return {"concurrency": concurrency}
        finally:
            conn.close()

    return await anyio.to_thread.run_sync(write)


@router.post("/sync/{action}")
def sync_control(request: Request, action: str):
    jm = request.app.state.jobs
    # Policy: a refused start is a no-op, reported as {"started": false} (the
    # Dashboard branches on it); refused pause/continue/stop are conflicts and
    # 409. Deliberately different shapes — don't "unify" them.
    if action == "start":
        return {"started": jm.start("sync")}
    if action == "backfill":
        return {"started": jm.start("backfill")}
    if action == "reindex":
        return {"started": jm.start("index")}
    if action == "sidecars":
        return {"started": jm.start("sidecars")}
    if action == "enrich":
        return {"started": jm.start("enrich")}
    if action == "identify":
        # Opt-in gate: never start identification (which sends audio to Shazam)
        # unless the owner has explicitly enabled it.
        conn = _open(request)
        try:
            if not store.get_library_settings(conn)["song_id_enabled"]:
                raise HTTPException(status_code=409, detail="enable song identification in settings first")
        finally:
            conn.close()
        return {"started": jm.start("identify")}
    if action == "pause":
        if not jm.pause():
            raise HTTPException(status_code=409, detail="no run in progress")
        return {"ok": True}
    if action == "continue":
        if not jm.resume():
            raise HTTPException(status_code=409, detail="no run in progress")
        return {"ok": True}
    if action == "stop":
        if not jm.stop():
            raise HTTPException(status_code=409, detail="no run in progress")
        return {"ok": True}
    raise HTTPException(status_code=400, detail=f"unknown action: {action}")


@router.get("/events")
def events(request: Request):
    """Server-Sent Events stream of sync progress."""
    jm = request.app.state.jobs

    def stream():
        q = jm.subscribe()
        try:
            while True:
                try:
                    event = q.get(timeout=15)
                except Empty:
                    yield ": keep-alive\n\n"  # heartbeat
                    continue
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            jm.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream")
