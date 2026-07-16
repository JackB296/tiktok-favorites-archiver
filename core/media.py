"""Slideshow asset recovery + fallback-audio selection for the Sync orchestrators.

Both orchestrators (``sync.run_sync`` and ``sync.run_backfill``) share this
work; the caller provides the one policy that differs after assets are ready:
encode an MP4 for Sync or simply classify recovery for backfill.
"""
import os
import shutil
import tempfile

from core import layout


def resolve_default_audio(download_dir, custom_name, bundled):
    """The fallback audio for a slideshow whose original sound is gone.

    Uses the user-uploaded track when one is configured and present on disk;
    otherwise the bundled default, so a missing or removed custom file degrades
    gracefully instead of breaking the encode.
    """
    if custom_name:
        path = layout.custom_default_audio(download_dir)
        if os.path.isfile(path):
            return path
    return bundled


def recover_slideshow_assets(deps, download_dir, item_id, image_urls, audio_url, on_ready):
    """Recover raw slideshow assets, then call ``on_ready(images, audio)``.

    Takes plain ``image_urls``/``audio_url`` so the resolver's response shape
    stays behind the Sync seam. Returns ``None`` when no source image was
    recovered. Temporary files remain available only for the callback, while
    raw Archive media is persisted before the callback runs.
    """
    if not image_urls:
        return None

    work = tempfile.mkdtemp(prefix="archive_slides_")
    try:
        images = []
        for index, url in enumerate(image_urls):
            path = os.path.join(work, f"slide_{index}.jpg")
            if deps.download_file(url, path):
                images.append(path)
        if not images:
            return None

        audio = deps.default_audio
        if audio_url:
            audio_tmp = os.path.join(work, "audio.mp3")
            if deps.download_file(audio_url, audio_tmp):
                audio = audio_tmp

        deps.save_assets(download_dir, item_id, images, audio)
        return on_ready(images, audio)
    finally:
        shutil.rmtree(work, ignore_errors=True)
