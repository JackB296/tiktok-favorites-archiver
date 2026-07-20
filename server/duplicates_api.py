"""Duplicate Radar report and background scan endpoints."""
import anyio
from fastapi import APIRouter, HTTPException, Request

from core import duplicates
from server.feature_api_common import items, open_db
from server.jobs import JobBusyError


router = APIRouter()


def _duplicate_report(request, conn, value):
    item_ids = sorted({
        item_id for group in value["groups"] for item_id in group["item_ids"]
    })
    projected = items(request, conn).selected(item_ids)
    by_id = {item["id"]: item for item in projected}
    return {
        **value,
        "groups": [
            {
                **group,
                "items": [
                    by_id[item_id] for item_id in group["item_ids"]
                    if item_id in by_id
                ],
            }
            for group in value["groups"]
        ],
    }


@router.get("/duplicates")
def duplicate_report(request: Request):
    conn = open_db(request)
    try:
        return _duplicate_report(request, conn, duplicates.report(conn))
    finally:
        conn.close()


@router.post("/duplicates/scan")
async def scan_duplicates(request: Request):
    def operation():
        conn = open_db(request)
        try:
            return _duplicate_report(
                request, conn,
                duplicates.scan(conn, request.app.state.download_dir),
            )
        finally:
            conn.close()

    try:
        return await anyio.to_thread.run_sync(
            lambda: request.app.state.jobs.run_when_idle(operation)
        )
    except JobBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))
