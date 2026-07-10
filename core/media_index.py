"""Inspect local Archive media and create reusable Gallery thumbnails."""
import json
import os
import subprocess
from collections import namedtuple


MediaFacts = namedtuple("MediaFacts", "duration_s width height codec file_size")
MediaIndex = namedtuple("MediaIndex", "duration_s width height codec file_size thumbnail_path")


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
    video = next(stream for stream in data.get("streams", []) if stream.get("codec_type") == "video")
    return MediaFacts(
        float(data.get("format", {}).get("duration") or 0),
        int(video.get("width") or 0),
        int(video.get("height") or 0),
        video.get("codec_name") or "unknown",
        os.path.getsize(path),
    )


def make_thumbnail(source, target, width, runner=subprocess.run):
    """Create a scaled WebP thumbnail without changing the source media."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    runner(
        ["ffmpeg", "-y", "-i", source, "-frames:v", "1", "-vf", f"scale={width}:-2", target],
        check=True,
        capture_output=True,
        text=True,
    )


def index_media(download_dir, item_id, thumbnail_width, inspect=inspect_media, make_thumbnail=make_thumbnail):
    """Inspect an Archive item and write its Gallery thumbnail.

    Slideshows use their first preserved raw image for the thumbnail; videos use
    the first video frame. Metadata always comes from the finished MP4.
    """
    movie = os.path.join(download_dir, f"{item_id}.mp4")
    facts = inspect(movie)
    raw_dir = os.path.join(download_dir, str(item_id))
    images = []
    if os.path.isdir(raw_dir):
        images = sorted(
            name for name in os.listdir(raw_dir)
            if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        )
    source = os.path.join(raw_dir, images[0]) if images else movie
    relative_thumb = f".archive/thumbnails/{item_id}.webp"
    make_thumbnail(source, os.path.join(download_dir, relative_thumb), thumbnail_width)
    return MediaIndex(*facts, relative_thumb)
