"""Slideshow asset recovery + fallback-audio selection for the Sync orchestrators.

Both orchestrators (``sync.run_sync`` and ``sync.run_backfill``) share this
work; the caller provides the one policy that differs after assets are ready:
encode an MP4 for Sync or simply classify recovery for backfill.
"""
import os
import shutil
import tempfile

from core import layout, slideshow_audio


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


def acquire_audio(deps, link, audio_url, destination):
    """Put this slideshow's soundtrack at ``destination``; say what it is.

    Returns ``(path, audio_source)``. ``audio_source`` is ``'original'`` only
    when a route actually produced this post's own sound — otherwise the
    encoder still gets a usable track, but the caller learns that the track is a
    substitute and must not be treated as evidence of what the post sounds like.
    """
    sources = getattr(deps, "audio_sources", None)
    if sources is not None:
        route = slideshow_audio.fetch_original(
            link, destination, sources,
            picker_audio_url=audio_url,
            fingerprints=getattr(deps, "fallback_fingerprints", ()) or (),
        )
        if route:
            return destination, slideshow_audio.ORIGINAL
    elif audio_url and deps.download_file(audio_url, destination):
        # No audio backends wired (a caller with a minimal Deps): keep the
        # single-attempt behaviour rather than losing the soundtrack entirely.
        return destination, slideshow_audio.ORIGINAL
    return deps.default_audio, slideshow_audio.FALLBACK


def recover_slideshow_assets(deps, download_dir, item_id, link, image_urls, audio_url,
                             on_ready):
    """Recover raw slideshow assets, then call ``on_ready(images, audio, source)``.

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

        audio, audio_source = acquire_audio(
            deps, link, audio_url, os.path.join(work, "audio.mp3"),
        )
        deps.save_assets(download_dir, item_id, images, audio)
        return on_ready(images, audio, audio_source)
    finally:
        shutil.rmtree(work, ignore_errors=True)
