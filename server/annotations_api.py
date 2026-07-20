"""Private curation annotation and review-session endpoints."""
import anyio
from fastapi import APIRouter, HTTPException, Request

from core import annotations
from server.feature_api_common import items, json_body, open_db


router = APIRouter()


@router.get("/items/{item_id}/annotation")
def get_annotation(request: Request, item_id: int):
    conn = open_db(request)
    try:
        value = annotations.get(conn, item_id)
        if value is None:
            raise HTTPException(status_code=404, detail="Favorite not found")
        return value
    finally:
        conn.close()


@router.put("/items/{item_id}/annotation")
async def update_annotation(request: Request, item_id: int):
    body = await json_body(request)

    def write():
        conn = open_db(request)
        try:
            return annotations.save(conn, item_id, body)
        finally:
            conn.close()

    try:
        return await anyio.to_thread.run_sync(write)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except KeyError:
        raise HTTPException(status_code=404, detail="Favorite not found")


@router.get("/curate/session")
def curate_session(
    request: Request, source: str = "unreviewed", limit: int = 20,
):
    conn = open_db(request)
    try:
        try:
            rows = annotations.session_rows(conn, source, limit)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        return {
            "source": source,
            "items": items(request, conn).project(rows),
        }
    finally:
        conn.close()
