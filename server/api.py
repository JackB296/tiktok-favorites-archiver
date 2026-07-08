"""FastAPI routes.

Thin wiring over the tested core/server logic. Compile-checked locally;
exercised with TestClient at the Docker phase (fastapi isn't installed here).
Each request opens its own SQLite connection (safe under WAL + busy_timeout).
"""
import os
import json
import tempfile
from queue import Empty

from fastapi import APIRouter, Request, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse

from core import config, store, importer, cobalt
from server import serializers

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


@router.get("/health")
def health():
    return {"status": "ok", "cobalt_reachable": cobalt.check_cobalt(config.COBALT_API_URL)}


@router.get("/howto", response_class=PlainTextResponse)
def howto():
    return HOWTO


@router.get("/items")
def list_items(request: Request, search: str = None, kind: str = None, status: str = None):
    conn = _open(request)
    try:
        rows = store.search_items(
            conn,
            query=search,
            kinds=[kind] if kind else None,
            statuses=[status] if status else None,
        )
        download_dir = _download_dir(request)
        return [serializers.item_to_public(row, download_dir) for row in rows]
    finally:
        conn.close()


@router.get("/items/{n}")
def get_item(request: Request, n: int):
    conn = _open(request)
    try:
        row = store.get_item(conn, n)
        if row is None:
            raise HTTPException(status_code=404, detail="item not found")
        return serializers.item_to_public(row, _download_dir(request))
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


@router.post("/sync/{action}")
def sync_control(request: Request, action: str):
    jm = request.app.state.jobs
    if action == "start":
        return {"started": jm.start("sync")}
    if action == "backfill":
        return {"started": jm.start("backfill")}
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
