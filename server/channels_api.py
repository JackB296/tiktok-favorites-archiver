"""Archive Channel CRUD and live collection resolution endpoints."""
import sqlite3

import anyio
from fastapi import APIRouter, HTTPException, Request

from core import channels
from server import archive_items
from server.feature_api_common import json_body, open_db


router = APIRouter()


@router.get("/channels")
def list_channels(request: Request):
    conn = open_db(request)
    try:
        return channels.list_channels(conn)
    finally:
        conn.close()


@router.post("/channels")
async def create_channel(request: Request):
    body = await json_body(request)

    def write():
        conn = open_db(request)
        try:
            return channels.create(conn, body)
        finally:
            conn.close()

    try:
        return await anyio.to_thread.run_sync(write)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except KeyError:
        raise HTTPException(status_code=404, detail="Smart collection not found")
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="a channel with that name already exists")


@router.delete("/channels/{channel_id}")
def delete_channel(request: Request, channel_id: int):
    conn = open_db(request)
    try:
        if not channels.delete(conn, channel_id):
            raise HTTPException(status_code=404, detail="Channel not found")
        return {"ok": True}
    finally:
        conn.close()


@router.get("/channels/{channel_id}/items")
def channel_items(request: Request, channel_id: int):
    conn = open_db(request)
    try:
        try:
            channel, item_ids = channels.item_ids(
                conn, channel_id, archive_items.gallery_preset_query,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Channel not found")
        except ValueError as error:
            raise HTTPException(status_code=400, detail=f"Channel is invalid: {error}")
        return {**channel, "item_ids": item_ids}
    finally:
        conn.close()
