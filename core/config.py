"""Central configuration constants and logging setup.

The runtime-overridable values (``COBALT_API_URL``, ``DOWNLOAD_DIR``,
``VIDEO_LINKS_FILE``, ``RETRY_DELAY``) are mutated in place on this module by the
CLI, so every other module that reads ``config.<NAME>`` at call time picks up the
override. (The original single file used module globals for this; across modules
we reference ``config.<NAME>`` instead of importing the value.)
"""
import os
import logging

COBALT_API_URL = os.environ.get("COBALT_API_URL", "http://localhost:9000/")
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}
RETRY_DELAY = 0.5  # Seconds between each download attempt
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "downloads")  # Directory to download videos
IMG_DIR = "img_dir"  # Temporary directory for creating slideshows
LAST_DOWNLOADED_LINK_FILE = "last_downloaded_link.txt"  # resume bookmark (last completed link)
VIDEO_LINKS_FILE = "user_data_tiktok.json"  # TikTok data export
MANIFEST_FILE = "manifest.csv"  # provenance sidecar (lives inside DOWNLOAD_DIR)
DB_FILE = os.environ.get("DB_FILE", os.path.join("data", "archive.db"))  # SQLite state store
DURATION_PER_IMAGE = 2.5  # Seconds each slide is shown in a slideshow
TARGET_SIZE = (1280, 720)  # Legacy slideshow frame size (superseded by the new encoder)
DEFAULT_AUDIO = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "default.mp3")
)  # bundled fallback audio (repo root)
# (connect timeout, read timeout) in seconds; read timeout is per-chunk, so a
# slow-but-progressing download is not killed while a truly stalled socket is.
REQUEST_TIMEOUT = (10, 30)
DOWNLOAD_CHUNK_SIZE = 1024 * 256  # 256 KB per streamed chunk

# Sync engine: worker concurrency + client-side Cobalt rate limit (env-overridable).
CONCURRENCY = int(os.environ.get("CONCURRENCY", "4"))          # simultaneous item workers
RATE_MAX_CALLS = int(os.environ.get("RATE_MAX_CALLS", "8"))    # at most this many Cobalt calls...
RATE_PERIOD = float(os.environ.get("RATE_PERIOD", "1.0"))      # ...per this many seconds
APP_PORT = int(os.environ.get("APP_PORT", "8080"))             # web server port


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
