"""Shared request helpers for feature-specific API routers."""
import json

from fastapi import HTTPException

from core import store
from server.archive_items import ArchiveItems


def open_db(request):
    return store.connect(request.app.state.db_path)


def items(request, conn):
    return ArchiveItems(conn, request.app.state.download_dir)


async def json_body(request):
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="request body must be valid JSON")
