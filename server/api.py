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

from fastapi import APIRouter, Request, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse

from core import config, store, importer, cobalt
from server.archive_items import ArchiveItems

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


_GALLERY_PRESET_FIELDS = {
    "search", "kind", "status", "order", "minDuration", "maxDuration",
    "minSize", "maxSize", "minWidth", "maxWidth", "minHeight", "maxHeight", "codec",
    "dateFrom", "dateTo", "orientation", "include", "exclude",
}


def _gallery_preset_filters(value):
    if not isinstance(value, dict):
        raise ValueError("filters must be an object")
    if any(key not in _GALLERY_PRESET_FIELDS or not isinstance(item, str) for key, item in value.items()):
        raise ValueError("filters contain an unsupported value")
    return {key: item for key, item in value.items() if item}


@router.get("/health")
def health():
    return {"status": "ok", "cobalt_reachable": cobalt.check_cobalt(config.COBALT_API_URL)}


@router.get("/howto", response_class=PlainTextResponse)
def howto():
    return HOWTO


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
        filters = _gallery_preset_filters(body.get("filters"))
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


@router.get("/items")
def list_items(request: Request, search: str = None, kind: str = None, status: str = None):
    conn = _open(request)
    try:
        return _archive_items(request, conn).list(
            query=search,
            kinds=[kind] if kind else None,
            statuses=[status] if status else None,
        )
    finally:
        conn.close()


@router.get("/items/page")
def page_items(
    request: Request,
    search: str = None,
    kind: str = None,
    status: str = None,
    limit: int = 50,
    cursor: int = None,
    order: str = "latest",
    min_duration: float = None,
    max_duration: float = None,
    min_size: int = None,
    max_size: int = None,
    min_width: int = None,
    max_width: int = None,
    min_height: int = None,
    max_height: int = None,
    codec: str = None,
    date_from: str = None,
    date_to: str = None,
    orientation: str = None,
    include: str = None,
    exclude: str = None,
):
    if order not in ("latest", "archive", "size_desc", "duration_desc", "duration_asc", "favorite_date_desc", "favorite_date_asc"):
        raise HTTPException(status_code=400, detail="unknown item order")
    conn = _open(request)
    try:
        return _archive_items(request, conn).page(
            query=search,
            kinds=[kind] if kind else None,
            statuses=[status] if status else None,
            limit=limit,
            cursor=cursor,
            order=order,
            min_duration=min_duration,
            max_duration=max_duration,
            min_size=min_size,
            max_size=max_size,
            min_width=min_width,
            max_width=max_width,
            min_height=min_height,
            max_height=max_height,
            codecs=[term.strip() for term in (codec or "").split(",") if term.strip()],
            date_from=date_from,
            date_to=date_to,
            orientations=[term.strip() for term in (orientation or "").split(",") if term.strip()],
            include=[term.strip() for term in (include or "").split(",") if term.strip()],
            exclude=[term.strip() for term in (exclude or "").split(",") if term.strip()],
        )
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
    item_ids = body.get("ids", [])
    if not isinstance(item_ids, list) or len(item_ids) > 100:
        raise HTTPException(status_code=400, detail="ids must contain at most 100 item IDs")
    conn = _open(request)
    try:
        return _archive_items(request, conn).selected([int(item_id) for item_id in item_ids])
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


@router.post("/import")
async def import_export(request: Request, file: UploadFile = File(...)):
    payload = await file.read()
    tmp_path = os.path.join(tempfile.gettempdir(), "user_data_tiktok.json")
    with open(tmp_path, "wb") as f:
        f.write(payload)
    conn = _open(request)
    try:
        try:
            return importer.import_all(conn, tmp_path, _download_dir(request))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid export: {e}")
    finally:
        conn.close()


@router.get("/status")
def status(request: Request):
    return request.app.state.jobs.status()


@router.get("/library-settings")
def library_settings(request: Request):
    conn = _open(request)
    try:
        return _library_settings(conn)
    finally:
        conn.close()


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


@router.post("/sync/{action}")
def sync_control(request: Request, action: str):
    jm = request.app.state.jobs
    if action == "start":
        return {"started": jm.start("sync")}
    if action == "backfill":
        return {"started": jm.start("backfill")}
    if action == "reindex":
        return {"started": jm.start("index")}
    if action == "pause":
        jm.pause()
        return {"ok": True}
    if action == "continue":
        jm.resume()
        return {"ok": True}
    if action == "stop":
        jm.stop()
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
