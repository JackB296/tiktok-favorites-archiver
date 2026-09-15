"""Central configuration constants and logging setup.

The runtime-overridable values (``COBALT_API_URL``, ``DOWNLOAD_DIR``,
``VIDEO_LINKS_FILE``, ``RETRY_DELAY``) are mutated in place on this module by the
CLI, so every other module that reads ``config.<NAME>`` at call time picks up the
override. (The original single file used module globals for this; across modules
we reference ``config.<NAME>`` instead of importing the value.)
"""
import os
import logging


class ConfigError(ValueError):
    """An environment variable holds a value the app cannot use."""


def _env_number(name, default, convert, *, minimum=None):
    """Read one numeric setting, naming the variable in any error.

    A typo in compose otherwise surfaces as a bare ``ValueError`` from
    ``int()`` during import — before logging exists and with no hint which
    of the dozen tunables was wrong. An empty value (compose users often leave
    ``KEY: ""``) falls back to the default; a malformed one fails loudly.
    """
    raw = os.environ.get(name)
    text = default if raw is None or raw.strip() == "" else raw.strip()
    try:
        value = convert(text)
    except (TypeError, ValueError):
        raise ConfigError(
            f"{name}={raw!r} is not a valid {convert.__name__}; "
            f"unset it to use the default ({default})"
        ) from None
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name}={raw!r} must be at least {minimum}")
    return value


def _env_int(name, default, minimum=None):
    return _env_number(name, str(default), int, minimum=minimum)


def _env_float(name, default, minimum=None):
    return _env_number(name, str(default), float, minimum=minimum)


COBALT_API_URL = os.environ.get("COBALT_API_URL", "http://localhost:9000/")
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "downloads")  # Directory to download videos
VIDEO_LINKS_FILE = "user_data_tiktok.json"  # TikTok data export
MANIFEST_FILE = "manifest.csv"  # provenance sidecar (lives inside DOWNLOAD_DIR)
DB_FILE = os.environ.get("DB_FILE", os.path.join("data", "archive.db"))  # SQLite state store
DURATION_PER_IMAGE = 2.5  # Seconds each slide is shown in a slideshow
DEFAULT_AUDIO = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "default.mp3")
)  # bundled fallback audio (repo root)
# (connect timeout, read timeout) in seconds; read timeout is per-chunk, so a
# slow-but-progressing download is not killed while a truly stalled socket is.
REQUEST_TIMEOUT = (10, 30)
DOWNLOAD_CHUNK_SIZE = 1024 * 256  # 256 KB per streamed chunk
# Hard cap per streamed file; a resolver that never stops sending must not
# fill the media volume (which also holds the database). TikTok videos are
# well under 1 GiB; raise via the environment for unusual sources.
DOWNLOAD_MAX_BYTES = _env_int("DOWNLOAD_MAX_BYTES", 2 * 1024 ** 3, minimum=1)
RETRY_DELAY = _env_float("RETRY_DELAY", 2.0, minimum=0.0)  # seconds between download retry attempts

# Sync engine: worker concurrency + client-side Cobalt rate limit (env-overridable).
CONCURRENCY = _env_int("CONCURRENCY", 4, minimum=1)          # simultaneous item workers
SOURCE_METADATA_WORKERS = _env_int(
    "SOURCE_METADATA_WORKERS", CONCURRENCY, minimum=1
)  # simultaneous yt-dlp metadata/comment workers
INDEX_WORKERS = _env_int(
    "INDEX_WORKERS", min(20, os.cpu_count() or 1), minimum=1
)  # simultaneous ffprobe/FFmpeg thumbnail workers
PORTABLE_METADATA_WORKERS = _env_int(
    "PORTABLE_METADATA_WORKERS", min(20, os.cpu_count() or 1), minimum=1,
)  # simultaneous stream-copy/validation workers
SIDECAR_WORKERS = _env_int(
    "SIDECAR_WORKERS", min(20, os.cpu_count() or 1), minimum=1,
)  # simultaneous NFO/poster workers
RATE_MAX_CALLS = _env_int("RATE_MAX_CALLS", 8, minimum=1)    # at most this many Cobalt calls...
RATE_PERIOD = _env_float("RATE_PERIOD", 1.0, minimum=0.0)    # ...per this many seconds
APP_PORT = _env_int("APP_PORT", 8080, minimum=1)             # web server port
# Extra Host names the web app may be reached at (comma-separated), for LAN,
# Tailscale, or reverse-proxy access — e.g. "nas.local,machine.tailnet.ts.net".
# Loopback names are always allowed; "*" allows any Host but gives up the
# DNS-rebinding protection the allowlist provides.
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "")

# Song identification (opt-in): a deliberately conservative outbound rate to
# Shazam, since it is an external service that can throttle or block heavy use.
SONG_ID_RATE_MAX_CALLS = _env_int("SONG_ID_RATE_MAX_CALLS", 1, minimum=1)  # 1 recognition...
SONG_ID_RATE_PERIOD = _env_float("SONG_ID_RATE_PERIOD", 2.0, minimum=0.0)  # ...per 2 seconds

# Fully local Local Lens analysis. The official Docker image provides these
# binaries and model; paths remain overridable for bare-metal development.
WHISPER_CPP_BIN = os.environ.get("WHISPER_CPP_BIN", "whisper-cli")
WHISPER_MODEL = os.environ.get(
    "WHISPER_MODEL", "/opt/whisper/models/ggml-base.bin",
)
TESSERACT_BIN = os.environ.get("TESSERACT_BIN", "tesseract")
ANALYSIS_TIMEOUT = _env_int("ANALYSIS_TIMEOUT", 900, minimum=1)
# Upper bound for every ffmpeg/ffprobe helper outside Local Lens (probe,
# thumbnail, poster, clip, mux, metadata embed, story render). A corrupt or
# crafted container must fail loudly instead of pinning a worker forever.
MEDIA_TOOL_TIMEOUT = _env_int("MEDIA_TOOL_TIMEOUT", 300, minimum=1)
ANALYSIS_MAX_OUTPUT_BYTES = _env_int(
    "ANALYSIS_MAX_OUTPUT_BYTES", 8 * 1024 * 1024, minimum=1
)
OCR_INTERVAL_SECONDS = _env_float("OCR_INTERVAL_SECONDS", 2.0, minimum=0.0)
OCR_MAX_FRAMES = _env_int("OCR_MAX_FRAMES", 600, minimum=1)
ANALYSIS_TRANSCRIPT_WORKERS = _env_int(
    "ANALYSIS_TRANSCRIPT_WORKERS", min(5, max(1, (os.cpu_count() or 1) // 4)), minimum=1,
)
ANALYSIS_OCR_WORKERS = _env_int(
    "ANALYSIS_OCR_WORKERS", min(8, os.cpu_count() or 1), minimum=1,
)


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
