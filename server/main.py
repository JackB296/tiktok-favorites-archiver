"""FastAPI application factory.

Serves the JSON API (``/api``), securely streamed range-capable media files
(``/media``), and the built frontend (``web/dist``) if present. Run with:
``uvicorn --factory server.main:create_app``.

No app is built at import time — importing this module must stay side-effect
free so tests can construct apps against their own temp databases. Run with
exactly one worker: the in-process JobManager is the single-run guard, so
``--workers >1`` would allow concurrent Archive runs.
"""
import mimetypes
import os
from email.utils import formatdate

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from core import archive_filesystem, config, scheduler, store
from server import media_range, request_security, spa
from server.api import router
from server.feature_api import router as feature_router
from server.jobs import JobManager


class SPAStaticFiles(StaticFiles):
    """Serve the built SPA, answering client routes with the app shell."""

    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and spa.is_client_route(path):
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404 and spa.is_client_route(path):
            return await super().get_response("index.html", scope)
        return response


def _file_chunks(opened, start, length):
    """Stream an already-securely-opened descriptor and always release it."""
    try:
        opened.seek(start)
        remaining = length
        while remaining:
            chunk = opened.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        opened.close()


def create_app(db_path=None, download_dir=None, jobs=None, allowed_hosts=None):
    """Build the app. ``jobs`` is injectable — tests supply a JobManager with
    fake runners so the whole HTTP surface is exercisable without moviepy or
    requests; production uses the real one. Production accepts only loopback
    Host names; ``allowed_hosts`` lets tests provide their synthetic Host."""
    db_path = db_path or config.DB_FILE
    download_dir = os.path.abspath(download_dir or config.DOWNLOAD_DIR)
    os.makedirs(download_dir, exist_ok=True)

    app = FastAPI(title="TikTok Favorites Archive")
    store.init_db(store.connect(db_path)).close()  # ensure schema exists at startup
    app.state.db_path = db_path
    app.state.download_dir = download_dir
    app.state.jobs = jobs if jobs is not None else JobManager(db_path, download_dir)
    app.state.scheduler = scheduler.Scheduler(db_path, app.state.jobs)
    request_policy = request_security.LocalRequestPolicy(
        request_security.DEFAULT_ALLOWED_HOSTS if allowed_hosts is None else allowed_hosts,
    )

    @app.middleware("http")
    async def protect_local_app(request, call_next):
        if not request_policy.allows(
            request.method,
            request.url.scheme,
            request.headers.get("host"),
            request.headers.get("origin"),
            request.headers.get(request_security.REQUEST_HEADER),
        ):
            return JSONResponse(status_code=403, content={"detail": "forbidden request source"})
        return await call_next(request)

    @app.on_event("startup")
    def start_scheduler():
        app.state.scheduler.start()

    @app.on_event("shutdown")
    def stop_scheduler():
        app.state.scheduler.stop()

    app.include_router(router)
    app.include_router(feature_router)

    @app.get("/media/{path:path}")
    def media(path: str, request: Request):
        try:
            opened = archive_filesystem.open_public_media(app.state.download_dir, path)
        except archive_filesystem.ArchivePathError:
            raise HTTPException(status_code=403, detail="forbidden")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="not found")

        file_stat = os.fstat(opened.fileno())
        try:
            selected = media_range.parse_byte_range(
                request.headers.get("range"), file_stat.st_size,
            )
        except media_range.RangeNotSatisfiable:
            opened.close()
            return Response(
                status_code=416,
                headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes */{file_stat.st_size}"},
            )
        start, end = selected or (0, file_stat.st_size - 1)
        length = max(0, end - start + 1)
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Last-Modified": formatdate(file_stat.st_mtime, usegmt=True),
        }
        status_code = 200
        if selected is not None:
            status_code = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{file_stat.st_size}"
        return StreamingResponse(
            _file_chunks(opened, start, length),
            status_code=status_code,
            media_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
            headers=headers,
        )

    # Serve the built SPA at "/" if it has been built (mounted last so /api and
    # /media take precedence). Client routes such as /gallery fall back to the
    # app shell so deep links and refreshes work.
    web_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "web", "dist"))
    if os.path.isdir(web_dist):
        app.mount("/", SPAStaticFiles(directory=web_dist, html=True), name="web")

    return app
