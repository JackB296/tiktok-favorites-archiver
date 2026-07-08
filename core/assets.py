"""Raw slideshow asset storage.

Saves each slideshow's **raw** images + audio to ``downloads/<n>/`` so the web
viewer can render an image carousel (with sound) instead of the MP4. Must be
called with the original downloaded images, before any slideshow padding.

Standard library only (file copies) — no PIL/moviepy needed, so it's directly
testable.
"""
import os
import shutil
import logging


def slideshow_dir(download_dir, n):
    return os.path.join(download_dir, str(n))


def save_assets(download_dir, n, image_paths, audio_path=None):
    """Copy raw images (``01.jpg``, ``02.jpg``, ...) and ``audio.mp3`` into
    ``downloads/<n>/``. Returns the folder path."""
    dest = slideshow_dir(download_dir, n)
    os.makedirs(dest, exist_ok=True)
    pad = max(2, len(str(len(image_paths))))
    for idx, src in enumerate(image_paths, 1):
        ext = os.path.splitext(src)[1] or ".jpg"
        out = os.path.join(dest, f"{idx:0{pad}d}{ext}")
        try:
            shutil.copy(src, out)
        except OSError as e:
            logging.error(f"Could not copy slide {src} -> {out}: {e}")
    if audio_path and os.path.exists(audio_path):
        try:
            shutil.copy(audio_path, os.path.join(dest, "audio.mp3"))
        except OSError as e:
            logging.error(f"Could not copy audio {audio_path}: {e}")
    return dest
