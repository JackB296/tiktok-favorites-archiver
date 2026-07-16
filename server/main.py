"""FastAPI application factory.

Serves the JSON API (``/api``), media files (``/media`` — range-capable via
``FileResponse``), and the built frontend (``web/dist``) if present. Run with:
``uvicorn --factory server.main:create_app``.

No app is built at import time — importing this module must stay side-effect
free so tests can construct apps against their own temp databases. Run with
exactly one worker: the in-process JobManager is the single-run guard, so
``--workers >1`` would allow concurrent Archive runs.
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from core import config, layout, store
from server import spa
from server.api import router
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


def create_app(db_path=None, download_dir=None, jobs=None):
    """Build the app. ``jobs`` is injectable — tests supply a JobManager with
    fake runners so the whole HTTP surface is exercisable without moviepy or
    requests; production uses the real one."""
    db_path = db_path or config.DB_FILE
    download_dir = os.path.abspath(download_dir or config.DOWNLOAD_DIR)
    os.makedirs(download_dir, exist_ok=True)

    app = FastAPI(title="TikTok Favorites Archive")
    store.init_db(store.connect(db_path)).close()  # ensure schema exists at startup
    app.state.db_path = db_path
    app.state.download_dir = download_dir
    app.state.jobs = jobs if jobs is not None else JobManager(db_path, download_dir)

    app.include_router(router)

    @app.get("/media/{path:path}")
    def media(path: str):
        base = app.state.download_dir
        full = os.path.normpath(os.path.join(base, path))
        if full != base and not full.startswith(base + os.sep):  # path-traversal guard
            raise HTTPException(status_code=403, detail="forbidden")
        if layout.is_private_relpath(os.path.relpath(full, base)):  # staged uploads, backups
            raise HTTPException(status_code=403, detail="forbidden")
        if not os.path.isfile(full):
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(full)  # FileResponse honors Range requests

    # Serve the built SPA at "/" if it has been built (mounted last so /api and
    # /media take precedence). Client routes such as /gallery fall back to the
    # app shell so deep links and refreshes work.
    web_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "web", "dist"))
    if os.path.isdir(web_dist):
        app.mount("/", SPAStaticFiles(directory=web_dist, html=True), name="web")

    return app
