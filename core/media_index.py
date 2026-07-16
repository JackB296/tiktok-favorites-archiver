"""The Archive's ffmpeg/ffprobe adapter.

Every shell-out to ffmpeg/ffprobe lives here: inspecting finished Archive
media, Gallery thumbnails, sidecar poster frames, song-identification clips,
and audio-stream probing. One injectable ``runner`` seam per function keeps
command construction, error mapping, and the write-then-atomic-publish
discipline in a single module.
"""
import json
import os
import subprocess
from collections import namedtuple

from core import layout


MediaIndex = namedtuple(
    "MediaIndex",
    "duration_s width height codec file_size thumbnail_path has_audio audio_silent",
    defaults=(True, None),
)

# A track whose peak never rises above this (dBFS) is treated as silent. Digital
# silence reads around -91 dB; real audio peaks near 0 dB.
SILENCE_MAX_DB = -50.0


class MediaFacts(namedtuple(
    "MediaFacts",
    "duration_s width height codec file_size has_audio audio_silent",
    defaults=(True, None),
)):
    __slots__ = ()

    def to_index(self, thumbnail_path):
        """Pair these inspected facts with their Gallery thumbnail path."""
        return MediaIndex(
            duration_s=self.duration_s,
            width=self.width,
            height=self.height,
            codec=self.codec,
            file_size=self.file_size,
            thumbnail_path=thumbnail_path,
            has_audio=self.has_audio,
            audio_silent=self.audio_silent,
        )


def measure_max_volume_db(path, runner=subprocess.run):
    """Peak audio level in dBFS via ffmpeg ``volumedetect``, or None if unreadable.
    A digitally silent track reports roughly -91 dB (or -inf)."""
    result = runner(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0?",
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    for line in (getattr(result, "stderr", "") or "").splitlines():
        if "max_volume:" in line:
            try:
                return float(line.split("max_volume:", 1)[1].strip().split()[0])
            except (ValueError, IndexError):
                return None
    return None


def inspect_media(path, runner=subprocess.run):
    """Read the primary video stream facts from one finished MP4."""
    result = runner(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height",
            "-of", "json", path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
    if video is None:
        # A bare StopIteration would be recorded as an empty index error.
        raise ValueError("no video stream in file")
    has_audio = any(stream.get("codec_type") == "audio" for stream in data.get("streams", []))
    audio_silent = None
    if has_audio:
        peak = measure_max_volume_db(path, runner)
        audio_silent = peak is not None and peak <= SILENCE_MAX_DB
    return MediaFacts(
        float(data.get("format", {}).get("duration") or 0),
        int(video.get("width") or 0),
        int(video.get("height") or 0),
        video.get("codec_name") or "unknown",
        os.path.getsize(path),
        has_audio,
        audio_silent,
    )


def file_fingerprint(path):
    """Cheap identity for a media file (size + mtime) to detect a stale index."""
    stat = os.stat(path)
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def make_thumbnail(source, target, width, runner=subprocess.run):
    """Create a scaled WebP thumbnail without changing the source media."""
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    runner(
        ["ffmpeg", "-y", "-i", source, "-frames:v", "1", "-vf", f"scale={width}:-2", target],
        check=True,
        capture_output=True,
        text=True,
    )


def make_poster(source, target, runner=subprocess.run):
    """Write one JPEG poster frame without changing the source media.

    The explicit muxer/codec flags let the target carry a temp suffix; the
    caller publishes it atomically.
    """
    runner(
        ["ffmpeg", "-y", "-i", source, "-frames:v", "1", "-q:v", "3", "-c:v", "mjpeg", "-f", "image2", target],
        check=True,
        capture_output=True,
        text=True,
    )


CLIP_SECONDS = 5   # Shazam needs only a few seconds; keep the upload small
CLIP_START = 0     # seconds into the source to start the clip


def extract_clip(source, target, start=CLIP_START, seconds=CLIP_SECONDS, runner=subprocess.run):
    """Write a ``seconds``-long mono 16 kHz WAV clip from ``source`` to ``target``.

    Returns ``target``. The source media is never modified.
    """
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    runner(
        [
            "ffmpeg", "-y",
            "-ss", str(start), "-t", str(seconds),
            "-i", source,
            "-vn", "-ac", "1", "-ar", "16000",
            target,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return target


def has_audio_stream(path, runner=subprocess.run):
    """True when ffprobe finds a decodable audio stream in the file.

    Tolerant by design — any probe failure reads as "no audio" so upload
    validation degrades to a clear rejection instead of a 500.
    """
    try:
        result = runner(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "json", path],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError:
        return False
    return any(stream.get("codec_type") == "audio" for stream in data.get("streams", []))


def index_media(download_dir, item_id, thumbnail_width, inspect=inspect_media, make_thumbnail=make_thumbnail):
    """Inspect an Archive item and write its Gallery thumbnail.

    Slideshows use their first preserved raw image for the thumbnail; videos use
    the first video frame. Metadata always comes from the finished MP4.
    """
    movie = layout.movie(download_dir, item_id)
    facts = inspect(movie)
    images = layout.slideshow_images(download_dir, item_id)
    source = os.path.join(layout.assets_dir(download_dir, item_id), images[0]) if images else movie
    relative_thumb = layout.thumbnail_relpath(item_id)
    make_thumbnail(source, os.path.join(download_dir, relative_thumb), thumbnail_width)
    return facts.to_index(relative_thumb)
