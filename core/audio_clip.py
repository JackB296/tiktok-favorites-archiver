"""Extract a short audio clip from an Archive item for song identification.

Videos carry their audio muxed inside the finished ``<n>.mp4``; slideshows keep
the raw soundtrack at ``downloads/<n>/audio.mp3``. Either way we cut one short
mono clip with the ffmpeg already bundled in the image — small enough to keep
the outbound Shazam request tiny, long enough to recognize.

``ffmpeg`` is invoked through an injected ``runner`` so extraction is testable
without decoding real media.
"""
import os
import subprocess

CLIP_SECONDS = 5   # Shazam needs only a few seconds; keep the upload small
CLIP_START = 0     # seconds into the source to start the clip


def source_audio(download_dir, item_id):
    """Best local audio source for an item.

    Prefers a slideshow's preserved ``audio.mp3`` (a clean audio-only file);
    otherwise the finished MP4, whose audio track ffmpeg reads directly.
    """
    slideshow_audio = os.path.join(download_dir, str(item_id), "audio.mp3")
    if os.path.isfile(slideshow_audio):
        return slideshow_audio
    return os.path.join(download_dir, f"{item_id}.mp4")


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
