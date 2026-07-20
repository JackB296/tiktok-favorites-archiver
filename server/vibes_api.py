"""Local Vibe Atlas search endpoints."""
from fastapi import APIRouter, HTTPException, Request

from core import vibes
from server.feature_api_common import items, open_db


router = APIRouter()


def _project_ranked(request, conn, ranked):
    projected = items(request, conn).selected(
        [result["item_id"] for result in ranked],
    )
    by_id = {item["id"]: item for item in projected}
    return [
        {**result, "item": by_id[result["item_id"]]}
        for result in ranked if result["item_id"] in by_id
    ]


@router.get("/vibes/search")
def vibe_search(request: Request, q: str = "", limit: int = 24):
    conn = open_db(request)
    try:
        try:
            ranked = vibes.search(conn, q, limit)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        return {"query": q.strip(), "results": _project_ranked(request, conn, ranked)}
    finally:
        conn.close()


@router.get("/vibes/related/{item_id}")
def vibe_related(request: Request, item_id: int, limit: int = 24):
    conn = open_db(request)
    try:
        try:
            ranked = vibes.related(conn, item_id, limit)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except KeyError:
            raise HTTPException(
                status_code=404, detail="Favorite has no searchable text",
            )
        return {
            "item_id": item_id,
            "results": _project_ranked(request, conn, ranked),
        }
    finally:
        conn.close()
