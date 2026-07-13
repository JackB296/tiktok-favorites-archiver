"""Archive-media work shared by Sync and Asset backfill.

This module owns temporary slideshow downloads, fallback-audio selection, and
raw asset persistence. Callers provide the one policy that differs after assets
are ready: encode an MP4 for Sync or simply classify recovery for backfill.
"""
import os
import shutil
import tempfile


def finished_movie_ids(names):
    """Sorted archive numbers of finished ``<n>.mp4`` files among directory entries."""
    return sorted(
        int(name[:-4])
        for name in names
        if name.endswith(".mp4") and name[:-4].isdigit()
    )


def recover_slideshow_assets(deps, download_dir, item_id, result, on_ready):
    """Recover raw slideshow assets, then call ``on_ready(images, audio)``.

    Returns ``None`` when no source image was recovered. Temporary files remain
    available only for the callback, while raw Archive media is persisted before
    the callback runs.
    """
    image_urls = result.images or []
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
        if result.audio:
            audio_tmp = os.path.join(work, "audio.mp3")
            if deps.download_file(result.audio, audio_tmp):
                audio = audio_tmp

        deps.save_assets(download_dir, item_id, images, audio)
        return on_ready(images, audio)
    finally:
        shutil.rmtree(work, ignore_errors=True)
