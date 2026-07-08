"""FastAPI application factory.

Serves the JSON API (``/api``), media files (``/media`` — range-capable via
``FileResponse``), and the built frontend (``web/dist``) if present. Run with:
``uvicorn server.main:app``.
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core import config, store
from server.api import router
from server.jobs import JobManager


def create_app(db_path=None, download_dir=None):
    db_path = db_path or config.DB_FILE
    download_dir = os.path.abspath(download_dir or config.DOWNLOAD_DIR)
    os.makedirs(download_dir, exist_ok=True)

    app = FastAPI(title="TikTok Favorites Archive")
    store.init_db(store.connect(db_path)).close()  # ensure schema exists at startup
    app.state.db_path = db_path
    app.state.download_dir = download_dir
    app.state.jobs = JobManager(db_path, download_dir)

    app.include_router(router)

    @app.get("/media/{path:path}")
    def media(path: str):
        base = app.state.download_dir
        full = os.path.normpath(os.path.join(base, path))
        if full != base and not full.startswith(base + os.sep):  # path-traversal guard
            raise HTTPException(status_code=403, detail="forbidden")
        if not os.path.isfile(full):
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(full)  # FileResponse honors Range requests

    # Serve the built SPA at "/" if it has been built (mounted last so /api and
    # /media take precedence).
    web_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "web", "dist"))
    if os.path.isdir(web_dist):
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")

    return app


app = create_app()
