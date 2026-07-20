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
import time
import uuid
import shutil
from queue import Empty
from urllib.parse import urlencode

import anyio
from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse, RedirectResponse, FileResponse
from starlette.background import BackgroundTask

from core import analysis, config, discovery, store, storage, snapshots, selection, run_catalog, scheduler, importer, import_history as archive_history, cobalt, curation, export, layout, verify, inventory, legacy_bootstrap, manual_media, media_index, songid, spotify, stats, lens, memory, stories, story_render
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


def _smart(request, preset_id, scope):
    conn = _open(request)
    try:
        preset, chosen = selection.ArchiveSelection.smart_collection(
            conn, preset_id, scope=scope,
            query_from_filters=archive_items.gallery_preset_query,
        )
        return conn, preset, chosen
    except KeyError:
        conn.close()
        raise HTTPException(status_code=404, detail="Smart collection not found")
    except ValueError as error:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Smart collection is invalid: {error}")


@router.get("/gallery-presets/{preset_id}/summary")
def smart_collection_summary(request: Request, preset_id: int):
    conn, preset, chosen = _smart(request, preset_id, "feed")
    try:
        ids = chosen.ids(conn)
        return {
            "id": preset["id"], "name": preset["name"],
            "count": len(ids), "first_item_id": ids[0] if ids else None,
        }
    finally:
        conn.close()


@router.get("/gallery-presets/{preset_id}/items")
def smart_collection_items(
    request: Request, preset_id: int, cursor: int | None = None,
    limit: int = 50, feed: bool = False,
):
    conn, preset, chosen = _smart(request, preset_id, "feed" if feed else "page")
    try:
        if feed:
            return {"id": preset["id"], "name": preset["name"], "item_ids": chosen.ids(conn)}
        query = dict(chosen.query)
        query["limit"] = max(1, min(limit, 100))
        if cursor is not None:
            query["cursor"] = cursor
        page = _archive_items(request, conn).page(**query)
        return {"id": preset["id"], "name": preset["name"], **page}
    finally:
        conn.close()


@router.get("/gallery-presets/{preset_id}/inventory")
def smart_collection_inventory(request: Request, preset_id: int):
    conn, preset, chosen = _smart(request, preset_id, "feed")
    try:
        ids = chosen.ids(conn)
        rows = store.get_items(conn, ids)
        ordered = [rows[item_id] for item_id in ids if item_id in rows]
        headers = {"Content-Disposition": f'attachment; filename="smart-collection-{preset_id}.csv"'}
        return StreamingResponse(
            inventory.csv_lines(ordered), media_type="text/csv; charset=utf-8",
            headers=headers,
        )
    finally:
        conn.close()


@router.post("/gallery-presets/{preset_id}/mark")
async def smart_collection_mark(request: Request, preset_id: int):
    body = await _json_body(request)
    if not isinstance(body, dict) or body.get("action") not in archive_items._MARK_ACTIONS:
        raise HTTPException(status_code=400, detail="invalid Smart collection action")
    dry_run = body.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise HTTPException(status_code=400, detail="dry_run must be a boolean")
    def operation():
        conn, _preset, chosen = _smart(request, preset_id, "set")
        try:
            return curation.mark(
                conn, _download_dir(request), body["action"], "ids",
                chosen.ids(conn), dry_run=dry_run,
            )
        finally:
            conn.close()
    try:
        return await _exclusive(request, operation)
    except JobBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))


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
    preset = request.query_params.get("preset")
    if preset is not None:
        if len(request.query_params) != 1:
            raise HTTPException(status_code=400, detail="preset cannot be combined with Gallery filters")
        try:
            preset_id = int(preset)
        except ValueError:
            raise HTTPException(status_code=400, detail="preset must be an integer")
        conn, _preset, chosen = _smart(request, preset_id, "feed")
        try:
            return chosen.ids(conn)
        finally:
            conn.close()
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
        return selection.ArchiveSelection.gallery(query, scope="feed").ids(conn)
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


@router.get("/stats")
def archive_stats(request: Request):
    """Archive analytics for the Stats tab — computed on demand, read-only."""
    conn = _open(request)
    try:
        return stats.compute_stats(conn)
    finally:
        conn.close()


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


@router.post("/items/{n}/played")
def item_played(request: Request, n: int):
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
        projector = _archive_items(request, conn)
        item_ids = list(dict.fromkeys(
            item_id
            for section in result["sections"]
            for item_id in section["item_ids"]
        ))
        items = projector.selected(item_ids)
        by_id = {item["id"]: item for item in items}
        return {
            **result,
            "sections": [
                {
                    **section,
                    "items": [
                        by_id[item_id]
                        for item_id in section["item_ids"]
                        if item_id in by_id
                    ],
                }
                for section in result["sections"]
            ],
        }
    finally:
        conn.close()


def _story_response(story):
    if story is None:
        return None
    return {
        **story,
        "rendered_url": (
            f"/media/{story['rendered_path']}" if story["rendered_path"] else None
        ),
    }


@router.get("/stories")
def list_stories(request: Request, limit: int = 200):
    conn = _open(request)
    try:
        return [
            _story_response(story)
            for story in stories.list_stories(conn, limit=limit)
        ]
    finally:
        conn.close()


@router.post("/stories")
async def create_story(request: Request):
    body = await _json_body(request)
    conn = _open(request)
    try:
        try:
            return _story_response(stories.create_story(conn, body))
        except stories.StoryError as error:
            raise HTTPException(status_code=400, detail=str(error))
    finally:
        conn.close()


@router.get("/stories/{story_id}")
def get_story(request: Request, story_id: int):
    conn = _open(request)
    try:
        story = stories.get_story(conn, story_id)
        if story is None:
            raise HTTPException(status_code=404, detail="story not found")
        return _story_response(story)
    finally:
        conn.close()


@router.patch("/stories/{story_id}")
async def update_story(request: Request, story_id: int):
    body = await _json_body(request)
    conn = _open(request)
    try:
        try:
            story = stories.update_story(conn, story_id, body)
        except stories.StoryError as error:
            raise HTTPException(status_code=400, detail=str(error))
        if story is None:
            raise HTTPException(status_code=404, detail="story not found")
        return _story_response(story)
    finally:
        conn.close()


@router.delete("/stories/{story_id}")
def delete_story(request: Request, story_id: int):
    conn = _open(request)
    try:
        current = stories.get_story(conn, story_id)
        if not stories.delete_story(conn, story_id):
            raise HTTPException(status_code=404, detail="story not found")
        if current and current["rendered_path"]:
            _remove_temp_files([layout.story_movie(_download_dir(request), story_id)])
        return {"ok": True}
    finally:
        conn.close()


@router.post("/stories/{story_id}/render")
async def render_story(request: Request, story_id: int):
    def operation():
        conn = _open(request)
        try:
            if stories.get_story(conn, story_id) is None:
                raise HTTPException(status_code=404, detail="story not found")
            return _story_response(
                story_render.render_story(
                    conn, _download_dir(request), story_id,
                )
            )
        finally:
            conn.close()

    try:
        return await _exclusive(request, operation)
    except JobBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except story_render.StoryRenderError as error:
        raise HTTPException(status_code=400, detail=str(error))


MAX_IMPORT_BYTES = 512 * 1024 * 1024  # far above any real TikTok export
MAX_REPLACEMENT_VIDEO_BYTES = 1024 * 1024 * 1024
MAX_REPLACEMENT_THUMBNAIL_BYTES = 20 * 1024 * 1024
MAX_DEFAULT_AUDIO_BYTES = 20 * 1024 * 1024
MAX_ANALYSIS_BYTES = 64 * 1024 * 1024


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


@router.get("/lens/status")
def lens_status(request: Request):
    conn = _open(request)
    try:
        return {
            **lens.status(conn),
            "coverage": analysis.coverage(conn, _download_dir(request)),
            "tools": analysis.tool_readiness(),
        }
    finally:
        conn.close()


@router.get("/items/{n}/captions")
def item_captions(request: Request, n: int):
    conn = _open(request)
    try:
        try:
            captions = lens.caption_segments(conn, n)
        except lens.LensError as error:
            raise HTTPException(status_code=404, detail=str(error))
        return {"item_id": n, "captions": captions}
    finally:
        conn.close()


@router.get("/lens/search")
def lens_search(
    request: Request,
    q: str = "",
    source: str | None = None,
    limit: int = 50,
):
    conn = _open(request)
    try:
        try:
            matches = lens.search_segments(
                conn, q, source=source, limit=max(1, min(limit, 100)),
            )
        except lens.LensError as error:
            raise HTTPException(status_code=400, detail=str(error))
        items = _archive_items(request, conn).selected(
            list(dict.fromkeys(match["item_id"] for match in matches))
        )
        by_id = {item["id"]: item for item in items}
        results = []
        for match in matches:
            item = by_id.get(match["item_id"])
            if item is None:
                continue
            start = f"{match['start_s']:g}"
            results.append({
                **match,
                "item": item,
                "feed_url": f"/?{urlencode({'item': match['item_id'], 'start_s': start})}",
            })
        return {"query": q, "results": results, **lens.status(conn)}
    finally:
        conn.close()


@router.post("/lens/import")
async def lens_import(request: Request, file: UploadFile = File(...)):
    staged = None
    try:
        staged = await _stage_upload(
            file, "archive-analysis-", ".json", max_bytes=MAX_ANALYSIS_BYTES,
        )
        document = lens.load_document(staged)

        def operation():
            conn = _open(request)
            try:
                return lens.import_document(conn, document)
            finally:
                conn.close()

        return await _exclusive(request, operation)
    except lens.LensError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except JobBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))
    finally:
        _remove_temp_files([staged] if staged else [])


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
    source_name = file.filename
    try:
        tmp_path = await _stage_upload(file, "tiktok-export-", ".json")

        def operation():
            conn = _open(request)
            try:
                return importer.import_all(
                    conn,
                    tmp_path,
                    _download_dir(request),
                    source_name=source_name,
                )
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


@router.get("/imports")
def list_imports(request: Request, limit: int = 50):
    conn = _open(request)
    try:
        return archive_history.list_imports(conn, limit=limit)
    finally:
        conn.close()


@router.get("/imports/{import_id}")
def get_import(request: Request, import_id: int):
    conn = _open(request)
    try:
        result = archive_history.get_import(conn, import_id)
        if result is None:
            raise HTTPException(status_code=404, detail="import not found")
        return result
    finally:
        conn.close()


@router.get("/storage-locations")
def storage_locations(request: Request):
    conn = _open(request)
    try:
        return storage.list_locations(conn)
    finally:
        conn.close()


@router.post("/storage-locations")
async def create_storage_location(request: Request):
    body = await _json_body(request)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Storage location must be an object")

    def operation():
        conn = _open(request)
        try:
            return storage.create_location(
                conn, body.get("name"), body.get("path"),
                _download_dir(request), request.app.state.db_path,
            )
        finally:
            conn.close()

    try:
        return await _exclusive(request, operation)
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except storage.StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/storage-locations/{location_id}")
async def update_storage_location(request: Request, location_id: int):
    body = await _json_body(request)
    if not isinstance(body, dict) or not body or set(body) - {"name", "path"}:
        raise HTTPException(status_code=400, detail="provide name and/or path")

    def operation():
        conn = _open(request)
        try:
            return storage.update_location(
                conn, location_id, body, _download_dir(request), request.app.state.db_path,
            )
        finally:
            conn.close()

    try:
        return await _exclusive(request, operation)
    except KeyError:
        raise HTTPException(status_code=404, detail="Storage location not found")
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except storage.StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/storage-locations/{location_id}/check")
async def check_storage_location(request: Request, location_id: int):
    def operation():
        conn = _open(request)
        try:
            return storage.check_location(
                conn, location_id, _download_dir(request), request.app.state.db_path,
            )
        finally:
            conn.close()
    try:
        return await _exclusive(request, operation)
    except KeyError:
        raise HTTPException(status_code=404, detail="Storage location not found")
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/storage-locations/{location_id}")
async def delete_storage_location(request: Request, location_id: int):
    def operation():
        conn = _open(request)
        try:
            storage.delete_location(conn, location_id)
            return {"ok": True}
        finally:
            conn.close()
    try:
        return await _exclusive(request, operation)
    except KeyError:
        raise HTTPException(status_code=404, detail="Storage location not found")
    except (JobBusyError, storage.StorageConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


def _storage_transfer_plan(request, body):
    if not isinstance(body, dict):
        raise ValueError("transfer must be an object")
    action = body.get("action")
    if action not in ("copy", "move", "restore"):
        raise ValueError("action must be copy, move, or restore")
    if type(body.get("location_id")) is not int:
        raise ValueError("location_id must be an integer")
    selector_body = {"action": "ignore"}
    for key in ("ids", "range", "filter"):
        if key in body:
            selector_body[key] = body[key]
    _action, selector_kind, selector_value, _dry = archive_items.parse_mark_request(selector_body)
    conn = _open(request)
    try:
        item_ids = selection.ArchiveSelection.bulk(selector_kind, selector_value).ids(conn)
        preview = storage.preview_restore(conn, body["location_id"], item_ids) \
            if action == "restore" else storage.preview_transfer(
                conn, _download_dir(request), body["location_id"], item_ids,
            )
    finally:
        conn.close()
    return {
        "action": action, "location_id": body["location_id"],
        "item_ids": item_ids, "preview": preview,
    }


@router.post("/storage-transfers/preview")
async def preview_storage_transfer(request: Request):
    try:
        plan = _storage_transfer_plan(request, await _json_body(request))
    except KeyError:
        raise HTTPException(status_code=404, detail="Storage location not found")
    except (ValueError, storage.StorageError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    plan_id = uuid.uuid4().hex
    plans = getattr(request.app.state, "storage_transfer_plans", None)
    if plans is None:
        plans = request.app.state.storage_transfer_plans = {}
    plans[plan_id] = {**plan, "created": time.monotonic()}
    return {"plan_id": plan_id, "action": plan["action"], **plan["preview"]}


@router.post("/storage-transfers")
async def start_storage_transfer(request: Request):
    body = await _json_body(request)
    plan_id = body.get("plan_id") if isinstance(body, dict) else None
    plans = getattr(request.app.state, "storage_transfer_plans", {})
    plan = plans.get(plan_id)
    if plan is None or time.monotonic() - plan["created"] > 900:
        raise HTTPException(status_code=409, detail="transfer preview is missing or stale")
    if plan["action"] == "move" and body.get("confirmation") != "MOVE AND DELETE LOCAL":
        raise HTTPException(status_code=400, detail="Move requires confirmation: MOVE AND DELETE LOCAL")
    conn = _open(request)
    try:
        current = storage.preview_restore(conn, plan["location_id"], plan["item_ids"]) \
            if plan["action"] == "restore" else storage.preview_transfer(
                conn, _download_dir(request), plan["location_id"], plan["item_ids"],
            )
    except (KeyError, storage.StorageError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    finally:
        conn.close()
    if current != plan["preview"]:
        raise HTTPException(status_code=409, detail="transfer preview is stale; preview again")
    kind = f"storage-{plan['action']}"
    if not request.app.state.jobs.start(
        kind, location_id=plan["location_id"], item_ids=plan["item_ids"],
    ):
        raise HTTPException(status_code=409, detail="an Archive run is currently active")
    plans.pop(plan_id, None)
    transfers = getattr(request.app.state, "storage_transfers", None)
    if transfers is None:
        transfers = request.app.state.storage_transfers = {}
    transfers[plan_id] = {
        "id": plan_id, "action": plan["action"], "location_id": plan["location_id"],
        "item_ids": plan["item_ids"],
    }
    return {"started": True, "id": plan_id}


@router.get("/storage-transfers/{transfer_id}")
def storage_transfer_status(request: Request, transfer_id: str):
    transfer = getattr(request.app.state, "storage_transfers", {}).get(transfer_id)
    if transfer is None:
        raise HTTPException(status_code=404, detail="Storage transfer not found")
    return {**transfer, **request.app.state.jobs.status()}


def _snapshot_resources(request):
    conn = _open(request)
    try:
        locations = store.list_storage_locations(conn)
    finally:
        conn.close()
    resources = []
    for location in locations:
        for snapshot in snapshots.list_snapshots(location["path"]):
            resources.append({
                **snapshot,
                "id": f"{location['id']}:{snapshot['name']}",
                "location_id": location["id"],
                "location_name": location["name"],
            })
    return resources


def _snapshot_resource(request, snapshot_id):
    found = next(
        (snapshot for snapshot in _snapshot_resources(request) if snapshot["id"] == snapshot_id),
        None,
    )
    if found is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return found


@router.get("/snapshots")
def list_archive_snapshots(request: Request):
    return _snapshot_resources(request)


@router.post("/snapshots")
async def create_archive_snapshot(request: Request):
    body = await _json_body(request)
    if not isinstance(body, dict) or type(body.get("location_id")) is not int:
        raise HTTPException(status_code=400, detail="location_id, name, and mode are required")
    conn = _open(request)
    try:
        location = store.get_storage_location(conn, body["location_id"])
    finally:
        conn.close()
    if location is None:
        raise HTTPException(status_code=404, detail="Storage location not found")
    if not request.app.state.jobs.start(
        "snapshot",
        db_path=request.app.state.db_path,
        destination_dir=location["path"],
        name=body.get("name"),
        mode=body.get("mode", "metadata"),
    ):
        raise HTTPException(status_code=409, detail="an Archive run is currently active")
    return {"started": True}


@router.get("/snapshots/{snapshot_id}")
def get_archive_snapshot(request: Request, snapshot_id: str):
    return _snapshot_resource(request, snapshot_id)


@router.post("/snapshots/{snapshot_id}/validate")
async def validate_archive_snapshot(request: Request, snapshot_id: str):
    resource = _snapshot_resource(request, snapshot_id)
    try:
        metadata = await _exclusive(
            request, lambda: snapshots.validate_snapshot(resource["path"])
        )
        return {"valid": True, "metadata": metadata}
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except snapshots.SnapshotError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/snapshots/{snapshot_id}/download")
def download_archive_snapshot(request: Request, snapshot_id: str):
    resource = _snapshot_resource(request, snapshot_id)
    if resource.get("mode") != "metadata" or resource["state"] != "complete":
        raise HTTPException(status_code=400, detail="only complete metadata snapshots can be downloaded")
    temporary = tempfile.mkdtemp(prefix="tiktok-snapshot-download-")
    archive = shutil.make_archive(
        os.path.join(temporary, resource["name"]), "zip",
        root_dir=resource["path"],
    )
    return FileResponse(
        archive,
        filename=f"{resource['name']}.zip",
        media_type="application/zip",
        background=BackgroundTask(shutil.rmtree, temporary, True),
    )


@router.post("/snapshot-restore/preview")
async def preview_snapshot_restore(request: Request):
    body = await _json_body(request)
    snapshot_id = body.get("snapshot_id") if isinstance(body, dict) else None
    resource = _snapshot_resource(request, snapshot_id)
    conn = _open(request)
    try:
        plan = snapshots.restore_plan(resource["path"], conn, _download_dir(request))
    except snapshots.SnapshotError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()
    plan_id = uuid.uuid4().hex
    plans = getattr(request.app.state, "snapshot_restore_plans", None)
    if plans is None:
        plans = request.app.state.snapshot_restore_plans = {}
    plans[plan_id] = {
        "resource": resource, "plan": plan, "created": time.monotonic(),
    }
    return {"plan_id": plan_id, **plan}


@router.post("/snapshot-restore")
async def start_snapshot_restore(request: Request):
    body = await _json_body(request)
    plan_id = body.get("plan_id") if isinstance(body, dict) else None
    saved = getattr(request.app.state, "snapshot_restore_plans", {}).get(plan_id)
    if saved is None or time.monotonic() - saved["created"] > 900:
        raise HTTPException(status_code=409, detail="restore preview is missing or stale")
    conn = _open(request)
    try:
        current = snapshots.restore_plan(
            saved["resource"]["path"], conn, _download_dir(request),
        )
    except snapshots.SnapshotError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    finally:
        conn.close()
    if current != saved["plan"]:
        raise HTTPException(status_code=409, detail="restore preview is stale; preview again")
    if current["requires_replace"] and body.get("confirmation") != "REPLACE ARCHIVE":
        raise HTTPException(status_code=400, detail="replacement requires confirmation: REPLACE ARCHIVE")
    conn = _open(request)
    try:
        location = store.get_storage_location(
            conn, saved["resource"]["location_id"],
        )
    finally:
        conn.close()
    if location is None:
        raise HTTPException(status_code=409, detail="Snapshot location is unavailable")
    if not request.app.state.jobs.start(
        "snapshot-restore",
        snapshot_path=saved["resource"]["path"],
        db_path=request.app.state.db_path,
        rollback_dir=location["path"],
        plan_token=current["token"],
        confirmation=body.get("confirmation"),
    ):
        raise HTTPException(status_code=409, detail="an Archive run is currently active")
    request.app.state.snapshot_restore_plans.pop(plan_id, None)
    return {"started": True}


# --- Spotify push -------------------------------------------------------------
# PKCE with the owner's own client id; scope playlist-modify-private only. The
# verifier lives in app state between /connect and /callback — a restart in
# that window just means pressing Connect again.

def _spotify_redirect_uri(request: Request):
    """Derived from how the owner reached the app, and shown in the Music tab
    so they register exactly this URI on their Spotify app."""
    return str(request.base_url).rstrip("/") + "/api/spotify/callback"


def _spotify_back(params):
    return RedirectResponse("/music?" + urlencode(params), status_code=303)


@router.get("/spotify/status")
def spotify_status(request: Request):
    conn = _open(request)
    try:
        auth = store.get_spotify_auth(conn)
        return {
            "connected": bool(auth and auth["refresh_token"]),
            "account_name": auth["account_name"] if auth else None,
            "client_id": auth["client_id"] if auth else None,
            "redirect_uri": _spotify_redirect_uri(request),
        }
    finally:
        conn.close()


@router.post("/spotify/connect")
async def spotify_connect(request: Request):
    body = await _json_body(request)
    client_id = (body.get("client_id") or "").strip() if isinstance(body, dict) else ""
    conn = _open(request)
    try:
        if not client_id:
            auth = store.get_spotify_auth(conn)
            client_id = (auth["client_id"] or "") if auth else ""
        if not client_id:
            raise HTTPException(status_code=400, detail="Enter your Spotify app's Client ID first.")
        store.save_spotify_auth(conn, client_id=client_id)
    finally:
        conn.close()
    verifier = spotify.generate_verifier()
    state = spotify.generate_verifier()[:32]
    request.app.state.spotify_pkce = {"verifier": verifier, "state": state}
    return {
        "authorize_url": spotify.authorize_url(
            client_id, _spotify_redirect_uri(request), spotify.pkce_challenge(verifier), state,
        ),
    }


@router.get("/spotify/callback")
def spotify_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Spotify's browser redirect target; always lands back on the Music tab."""
    if error:
        return _spotify_back({"spotify_error": error})
    pkce = getattr(request.app.state, "spotify_pkce", None)
    if not code or not pkce or state != pkce["state"]:
        return _spotify_back({"spotify_error": "That sign-in attempt is stale — press Connect again."})
    conn = _open(request)
    try:
        auth = store.get_spotify_auth(conn)
        tokens = spotify.exchange_code(
            spotify.default_http, auth["client_id"], _spotify_redirect_uri(request),
            code, pkce["verifier"],
        )
        account = spotify.get_account(spotify.default_http, tokens["access_token"])
        store.save_spotify_auth(
            conn,
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            expires_at=tokens["expires_at"],
            account_name=account["name"],
        )
        request.app.state.spotify_pkce = None
        return _spotify_back({"spotify": "connected"})
    except spotify.SpotifyError as exc:
        return _spotify_back({"spotify_error": str(exc)})
    finally:
        conn.close()


@router.post("/spotify/disconnect")
def spotify_disconnect(request: Request):
    conn = _open(request)
    try:
        store.clear_spotify_auth(conn)
        return {"connected": False}
    finally:
        conn.close()


@router.post("/song-playlists/{playlist_id}/push")
def push_song_playlist(request: Request, playlist_id: int):
    """Push one saved playlist to the connected account. Deliberately not
    behind the run guard: it touches only song/playlist rows and Spotify."""
    conn = _open(request)
    try:
        return spotify.push_playlist(conn, playlist_id)
    except spotify.SpotifyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


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


@router.get("/run-catalog")
def archive_run_catalog():
    return run_catalog.public_catalog()


@router.get("/pipeline-settings")
def pipeline_settings(request: Request):
    conn = _open(request)
    try:
        return store.get_pipeline_settings(conn, "sync")
    finally:
        conn.close()


@router.put("/pipeline-settings")
async def update_pipeline_settings(request: Request):
    body = await _json_body(request)
    phases = body.get("phases") if isinstance(body, dict) else None
    try:
        validated = run_catalog.validate_pipeline("sync", phases)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    conn = _open(request)
    try:
        return store.set_pipeline_settings(conn, "sync", list(validated))
    finally:
        conn.close()


@router.post("/run-history/{run_id}/retry")
def retry_archive_run(request: Request, run_id: int):
    try:
        result = request.app.state.jobs.retry(run_id)
    except ValueError as error:
        message = str(error)
        raise HTTPException(
            status_code=404 if "not found" in message else 400,
            detail=message,
        )
    if not result["started"]:
        raise HTTPException(status_code=409, detail="an Archive run is currently active")
    return result


@router.get("/run-schedules")
def run_schedules(request: Request):
    conn = _open(request)
    try:
        return store.list_run_schedules(conn)
    finally:
        conn.close()


@router.post("/run-schedules")
async def create_run_schedule(request: Request):
    body = await _json_body(request)
    try:
        values = scheduler.prepare(body, scheduler.datetime.now(scheduler.timezone.utc))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    conn = _open(request)
    try:
        return store.save_run_schedule(conn, values)
    finally:
        conn.close()


@router.patch("/run-schedules/{schedule_id}")
async def update_run_schedule(request: Request, schedule_id: int):
    body = await _json_body(request)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="schedule must be an object")
    conn = _open(request)
    try:
        current = store.get_run_schedule(conn, schedule_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Run schedule not found")
        source = {**current, **body}
        try:
            values = scheduler.prepare(source, scheduler.datetime.now(scheduler.timezone.utc))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        return store.save_run_schedule(conn, values, schedule_id)
    finally:
        conn.close()


@router.delete("/run-schedules/{schedule_id}")
def delete_run_schedule(request: Request, schedule_id: int):
    conn = _open(request)
    try:
        if not store.delete_run_schedule(conn, schedule_id):
            raise HTTPException(status_code=404, detail="Run schedule not found")
        return {"ok": True}
    finally:
        conn.close()


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
    try:
        kind = run_catalog.kind_for_action(action)
    except ValueError:
        kind = None
    if kind == "identify":
        # Opt-in gate: never start identification (which sends audio to Shazam)
        # unless the owner has explicitly enabled it.
        conn = _open(request)
        try:
            if not store.get_library_settings(conn)["song_id_enabled"]:
                raise HTTPException(status_code=409, detail="enable song identification in settings first")
        finally:
            conn.close()
    if kind is not None:
        return {"started": jm.start(kind)}
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
