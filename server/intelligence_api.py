"""HTTP adapter for archive discovery and memory features.

These routes share the Archive intelligence seam: both turn durable Archive
metadata into ways to find and revisit Favorites without touching media.
"""
from fastapi import APIRouter, HTTPException, Request

from core import discovery, memory
from server.api import _archive_items, _open

router = APIRouter()


def _discovery_list(request, kind, q, order, cursor, limit):
    conn = _open(request)
    try:
        try:
            return discovery.list_entities(
                conn, kind, search=q, order=order, cursor=cursor, limit=limit,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
    finally:
        conn.close()


@router.get("/creators")
def creators(request: Request, q: str = "", order: str = "frequency", cursor: int = 0, limit: int = 50):
    return _discovery_list(request, "creator", q, order, cursor, limit)


@router.get("/creators/{creator_id}")
def creator(request: Request, creator_id: int):
    conn = _open(request)
    try:
        value = discovery.get_entity(conn, "creator", creator_id)
        if value is None:
            raise HTTPException(status_code=404, detail="Creator not found")
        return value
    finally:
        conn.close()


@router.get("/hashtags")
def hashtags(request: Request, q: str = "", order: str = "frequency", cursor: int = 0, limit: int = 50):
    return _discovery_list(request, "hashtag", q, order, cursor, limit)


@router.get("/hashtags/{hashtag_id}")
def hashtag(request: Request, hashtag_id: int):
    conn = _open(request)
    try:
        value = discovery.get_entity(conn, "hashtag", hashtag_id)
        if value is None:
            raise HTTPException(status_code=404, detail="Hashtag not found")
        return value
    finally:
        conn.close()


@router.post("/items/{n}/played")
def record_played_item(request: Request, n: int):
    conn = _open(request)
    try:
        try:
            return memory.record_play(conn, n)
        except memory.MemoryError as error:
            raise HTTPException(status_code=404, detail=str(error))
    finally:
        conn.close()
@router.get("/memories")
def memories(request: Request, date: str | None = None, limit: int = 12):
    conn = _open(request)
    try:
        try:
            result = memory.build_sections(conn, on_date=date, limit=limit)
        except memory.MemoryError as error:
            raise HTTPException(status_code=400, detail=str(error))
        item_ids = list(dict.fromkeys(
            item_id for section in result["sections"] for item_id in section["item_ids"]
        ))
        by_id = {item["id"]: item for item in _archive_items(request, conn).selected(item_ids)}
        return {
            **result,
            "sections": [{
                **section,
                "items": [by_id[item_id] for item_id in section["item_ids"] if item_id in by_id],
            } for section in result["sections"]],
        }
    finally:
        conn.close()
