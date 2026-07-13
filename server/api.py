"""FastAPI routes.

Thin wiring over the tested core/server logic. Compile-checked locally;
exercised with TestClient at the Docker phase (fastapi isn't installed here).
Each request opens its own SQLite connection (safe under WAL + busy_timeout).
"""
import os
import json
import sqlite3
import tempfile
from queue import Empty

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse

from core import config, store, importer, cobalt, verify, inventory, legacy_bootstrap, manual_media
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
    settings = dict(store.get_library_settings(conn))
    settings["index"] = store.library_index_status(conn)
    return settings


def _gallery_term_list(body):
    if not isinstance(body, dict):
        raise ValueError("list must be an object")
    name = body.get("name")
    mode = body.get("mode")
    terms = body.get("terms")
    if not isinstance(name, str) or not (name := name.strip()) or len(name) > 80:
        raise ValueError("name must be between 1 and 80 characters")
    if mode not in ("include", "exclude"):
        raise ValueError("mode must be include or exclude")
    if not isinstance(terms, list) or not 1 <= len(terms) <= 100:
        raise ValueError("terms must contain 1 to 100 entries")
    cleaned = []
    for term in terms:
        if not isinstance(term, str):
            raise ValueError("each term must be 1 to 100 characters")
        term = term.strip()
        if not term or len(term) > 100:
            raise ValueError("each term must be 1 to 100 characters")
        if term not in cleaned:
            cleaned.append(term)
    return name, mode, cleaned


def _playback_queue(body):
    if not isinstance(body, dict):
        raise ValueError("queue must be an object")
    name = body.get("name")
    item_ids = body.get("item_ids")
    if not isinstance(name, str) or not (name := name.strip()) or len(name) > 80:
        raise ValueError("name must be between 1 and 80 characters")
    if (
        not isinstance(item_ids, list)
        or not 1 <= len(item_ids) <= 100
        or len(set(item_ids)) != len(item_ids)
        or any(type(item_id) is not int or item_id < 1 for item_id in item_ids)
    ):
        raise ValueError("item_ids must contain 1 to 100 unique positive integer IDs")
    return name, item_ids


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


@router.get("/gallery-presets")
def list_gallery_presets(request: Request):
    conn = _open(request)
    try:
        return store.list_gallery_presets(conn)
    finally:
        conn.close()


@router.post("/gallery-presets")
async def create_gallery_preset(request: Request):
    body = await request.json()
    name = body.get("name") if isinstance(body, dict) else None
    if not isinstance(name, str) or not (name := name.strip()) or len(name) > 80:
        raise HTTPException(status_code=400, detail="name must be between 1 and 80 characters")
    try:
        filters = archive_items.gallery_preset_filters(body.get("filters"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    conn = _open(request)
    try:
        preset_id = store.save_gallery_preset(conn, name, filters)
        return {"id": preset_id, "name": name, "filters": filters}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="a preset with that name already exists")
    finally:
        conn.close()


@router.delete("/gallery-presets/{preset_id}")
def delete_gallery_preset(request: Request, preset_id: int):
    conn = _open(request)
    try:
        if not store.delete_gallery_preset(conn, preset_id):
            raise HTTPException(status_code=404, detail="preset not found")
        return {"ok": True}
    finally:
        conn.close()


@router.get("/gallery-term-lists")
def list_gallery_term_lists(request: Request):
    conn = _open(request)
    try:
        return store.list_gallery_term_lists(conn)
    finally:
        conn.close()


@router.post("/gallery-term-lists")
async def create_gallery_term_list(request: Request):
    try:
        name, mode, terms = _gallery_term_list(await request.json())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    conn = _open(request)
    try:
        list_id = store.save_gallery_term_list(conn, name, mode, terms)
        return {"id": list_id, "name": name, "mode": mode, "terms": terms}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="a term list with that name already exists")
    finally:
        conn.close()


@router.delete("/gallery-term-lists/{list_id}")
def delete_gallery_term_list(request: Request, list_id: int):
    conn = _open(request)
    try:
        if not store.delete_gallery_term_list(conn, list_id):
            raise HTTPException(status_code=404, detail="term list not found")
        return {"ok": True}
    finally:
        conn.close()


@router.get("/playback-queues")
def list_playback_queues(request: Request):
    conn = _open(request)
    try:
        return store.list_playback_queues(conn)
    finally:
        conn.close()


@router.post("/playback-queues")
async def create_playback_queue(request: Request):
    try:
        name, item_ids = _playback_queue(await request.json())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    conn = _open(request)
    try:
        queue_id = store.save_playback_queue(conn, name, item_ids)
        return {"id": queue_id, "name": name, "item_ids": item_ids}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="a playback queue with that name already exists")
    finally:
        conn.close()


@router.delete("/playback-queues/{queue_id}")
def delete_playback_queue(request: Request, queue_id: int):
    conn = _open(request)
    try:
        if not store.delete_playback_queue(conn, queue_id):
            raise HTTPException(status_code=404, detail="playback queue not found")
        return {"ok": True}
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


@router.post("/items/selection")
async def item_selection(request: Request):
    body = await request.json()
    item_ids = body.get("ids", []) if isinstance(body, dict) else None
    if (
        not isinstance(item_ids, list)
        or len(item_ids) > 100
        or any(type(item_id) is not int or item_id < 1 for item_id in item_ids)
    ):
        raise HTTPException(status_code=400, detail="ids must contain at most 100 positive integer item IDs")
    conn = _open(request)
    try:
        return _archive_items(request, conn).selected(item_ids)
    finally:
        conn.close()


@router.post("/items/requeue")
async def requeue_items(request: Request):
    """Queue selected failed/missing favorites without disturbing healthy media."""
    body = await request.json()
    item_ids = body.get("ids") if isinstance(body, dict) else None
    if (
        not isinstance(item_ids, list)
        or not 1 <= len(item_ids) <= 100
        or any(type(item_id) is not int or item_id < 1 for item_id in item_ids)
    ):
        raise HTTPException(status_code=400, detail="ids must contain 1 to 100 positive integer item IDs")
    if request.app.state.jobs.is_running():
        raise HTTPException(status_code=409, detail="wait for the current run to finish")
    conn = _open(request)
    try:
        return verify.requeue_selected(conn, _download_dir(request), item_ids)
    finally:
        conn.close()


@router.post("/items/mark")
async def mark_items(request: Request):
    """Bulk offload/ignore marking by explicit ids, id range, or Gallery filter."""
    body = await request.json()
    try:
        action, kind, value, dry_run = archive_items.parse_mark_request(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if request.app.state.jobs.is_running():
        raise HTTPException(status_code=409, detail="wait for the current run to finish")
    conn = _open(request)
    try:
        if kind == "ids":
            ids = value
        elif kind == "range":
            ids = store.item_ids_in_range(conn, value["first_id"], value["last_id"])
        else:
            ids = store.item_ids_matching(conn, **value)
        if dry_run:
            return {"matched": len(ids), "changed": 0, "dry_run": True}
        if action == "offload":
            changed = store.set_offloaded(conn, ids, offloaded=True)
        elif action == "unoffload":
            result = verify.unoffload_items(conn, _download_dir(request), ids)
            return {"matched": len(ids), **result}
        else:
            changed = store.set_ignored(conn, ids, ignored=(action == "ignore"))
        return {"matched": len(ids), "changed": changed}
    finally:
        conn.close()


@router.get("/items/offload-suggestion")
def items_offload_suggestion(request: Request):
    conn = _open(request)
    try:
        return verify.offload_suggestion(conn, _download_dir(request))
    finally:
        conn.close()


@router.get("/items/{n}")
def get_item(request: Request, n: int):
    conn = _open(request)
    try:
        item = _archive_items(request, conn).get(n)
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")
        return item
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
                f.write(chunk)
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
    upload_dir = os.path.join(_download_dir(request), ".archive", "uploads")
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

        return request.app.state.jobs.run_when_idle(operation)
    except JobBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except manual_media.MediaReplacementError as error:
        raise HTTPException(status_code=400, detail=str(error))
    finally:
        _remove_temp_files([path for path in (staged_video, staged_thumbnail) if path])


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

        return request.app.state.jobs.run_when_idle(operation)
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
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

        return request.app.state.jobs.run_when_idle(lambda: operation(plan))
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
            if conn.execute("SELECT 1 FROM item LIMIT 1").fetchone() is not None:
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
    if request.app.state.jobs.is_running():
        raise HTTPException(status_code=409, detail="wait for the current run to finish")
    conn = _open(request)
    try:
        return verify.requeue_missing(conn, _download_dir(request))
    finally:
        conn.close()


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
    body = await request.json()
    conn = _open(request)
    try:
        store.set_library_settings(
            conn,
            index_enabled=body.get("index_enabled"),
            thumbnail_width=body.get("thumbnail_width"),
        )
        return _library_settings(conn)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))
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
    body = await request.json()
    concurrency = body.get("concurrency") if isinstance(body, dict) else None
    if type(concurrency) is not int or not 1 <= concurrency <= 16:
        raise HTTPException(status_code=400, detail="concurrency must be an integer from 1 to 16")
    conn = _open(request)
    try:
        store.set_run_state(conn, concurrency=concurrency)
        return {"concurrency": concurrency}
    finally:
        conn.close()


@router.post("/sync/{action}")
def sync_control(request: Request, action: str):
    jm = request.app.state.jobs
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
