"""Archive-media layout: where every file for a Favorite lives (stdlib).

The single answer to "where does Archive media for Favorite ``n`` live?".
Workers, the projection adapter, and the web routes import this vocabulary
instead of re-deriving path conventions.

Layout under the download directory:

    <n>.mp4                        finished Archive media
    <n>/01.jpg ...  <n>/audio.mp3  raw slideshow assets
    <n>.nfo  <n>.jpg               media-server sidecars
    .archive/thumbnails/<n>.webp   Gallery thumbnail
    .archive/custom-thumbnails/    user-supplied thumbnails
    .archive/replaced/<n>.mp4      backup of a manually replaced video
    .archive/uploads/              staged multipart uploads
    .archive/default-audio.mp3     user-supplied slideshow fallback track
"""
import os

# Extensions a raw slideshow image may carry (compare lowercased names).
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
# Suffixes of temp files left behind by crashed downloads or encodes.
TEMP_SUFFIXES = (".part", ".part.mp4", ".tmp")
# App-managed state directory inside the media volume.
ARCHIVE_DIR = ".archive"


def movie_name(n):
    return f"{n}.mp4"


def movie(download_dir, n):
    """The finished Archive media for Favorite ``n``."""
    return os.path.join(download_dir, f"{n}.mp4")


def assets_dir(download_dir, n):
    """The raw slideshow asset folder for Favorite ``n``."""
    return os.path.join(download_dir, str(n))


def slideshow_audio(download_dir, n):
    """A slideshow's preserved raw soundtrack."""
    return os.path.join(download_dir, str(n), "audio.mp3")


def nfo(download_dir, n):
    return os.path.join(download_dir, f"{n}.nfo")


def poster(download_dir, n):
    return os.path.join(download_dir, f"{n}.jpg")


def thumbnail_relpath(n):
    """Gallery thumbnail path, relative to the download dir (as stored in the DB)."""
    return f".archive/thumbnails/{n}.webp"


def thumbnails_dir(download_dir):
    return os.path.join(download_dir, ARCHIVE_DIR, "thumbnails")


def custom_thumbnail_relpath(n, extension):
    return f".archive/custom-thumbnails/{n}.{extension}"


def replaced_movie(download_dir, n):
    """Backup location of a manually replaced video (most recent only)."""
    return os.path.join(download_dir, ARCHIVE_DIR, "replaced", f"{n}.mp4")


def uploads_dir(download_dir):
    """Staging area for multipart uploads, on the same volume as the archive."""
    return os.path.join(download_dir, ARCHIVE_DIR, "uploads")


def custom_default_audio(download_dir):
    """The user-supplied slideshow fallback track (persists in the media volume)."""
    return os.path.join(download_dir, ARCHIVE_DIR, "default-audio.mp3")


def is_private_relpath(relpath):
    """True for app-internal areas that must never be served over ``/media``:
    staged uploads and replaced-video backups. Thumbnails stay servable.

    Compared case-insensitively: on a case-insensitive filesystem (macOS
    bare-metal runs) ``.ARCHIVE/replaced/1.mp4`` resolves to the real backup,
    so a case-sensitive denylist would be bypassable.
    """
    parts = os.path.normpath(relpath).lower().split(os.sep)
    return len(parts) >= 2 and parts[0] == ARCHIVE_DIR and parts[1] in ("uploads", "replaced")


def is_finished_movie_name(name):
    """Exactly ``<n>.mp4`` — a crashed encode's ``<n>.mp4.part.mp4`` temp and
    the ``.part``/``.tmp`` families must never count as finished media."""
    stem = name.split(".")[0]
    return stem.isdigit() and name == f"{stem}.mp4"


def finished_movie_ids(names):
    """Sorted archive numbers of finished ``<n>.mp4`` files among directory entries."""
    return sorted(int(name[:-4]) for name in names if is_finished_movie_name(name))


def slideshow_images(download_dir, n):
    """Sorted raw slideshow image names for Favorite ``n`` (``[]`` when none)."""
    raw = assets_dir(download_dir, n)
    if not os.path.isdir(raw):
        return []
    return sorted(name for name in os.listdir(raw) if name.lower().endswith(IMAGE_EXTS))


def source_audio(download_dir, n):
    """Best local audio source for song identification.

    Prefers a slideshow's preserved ``audio.mp3`` (a clean audio-only file);
    otherwise the finished MP4, whose audio track ffmpeg reads directly.
    """
    preserved = slideshow_audio(download_dir, n)
    if os.path.isfile(preserved):
        return preserved
    return movie(download_dir, n)
