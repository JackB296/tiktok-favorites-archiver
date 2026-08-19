"""Fetching a slideshow's *original* soundtrack, and knowing when we failed.

A photo post's sound is fetched separately from its images, and that fetch is
the fragile half. The old behaviour was to try once and, on any failure, write
the bundled default track into the archive — which loses the distinction between
"this post sounds like this" and "we could not get this post's sound", because
both end up as a perfectly ordinary ``<n>/audio.mp3``.

This module replaces the single attempt with independent routes, and — just as
importantly — refuses to call a route successful unless the bytes it produced
are really a usable soundtrack:

1. the ``audio`` URL from the picker response the caller already has;
2. a fresh audio-only Cobalt resolve (a different code path inside Cobalt,
   which is what makes it worth trying after route 1 fails);
3. yt-dlp's audio-only rendition, which does not involve Cobalt at all.

Every candidate is checked for being non-empty, decodable, audible, and not
byte-identical to a known fallback track before it is accepted, so a route that
"succeeds" while returning a zero-byte tunnel or a copy of the default cannot
poison the archive.

The network and probing backends are injected, so the route logic is testable
without Cobalt, yt-dlp, or ffmpeg.
"""
import logging
import os

from core import fallback_audio


# What produced the soundtrack now stored for a favorite.
ORIGINAL = "original"    # the post's real sound
FALLBACK = "fallback"    # a substituted default track; not this post's sound


class AudioSources:
    """The backends ``fetch_original`` uses, each independently replaceable."""

    def __init__(self, download_file=None, resolve_audio=None, ytdlp_audio=None,
                 inspect_audio=None):
        self.download_file = download_file
        self.resolve_audio = resolve_audio
        self.ytdlp_audio = ytdlp_audio
        self.inspect_audio = inspect_audio


def build_sources(limiter=None):
    """Wire the real backends (lazy-imports the heavy dependencies)."""
    from core import cobalt, download, media_index, ytdlp_adapter
    return AudioSources(
        download_file=download.download_file,
        resolve_audio=lambda link: cobalt.resolve_audio(link, limiter=limiter),
        ytdlp_audio=ytdlp_adapter.download_audio,
        inspect_audio=media_index.inspect_audio,
    )


def is_usable(path, sources, fingerprints=()):
    """Whether ``path`` holds a real soundtrack we are willing to archive.

    Rejects the three ways a "successful" fetch still gives us nothing: an empty
    file (Cobalt's zero-byte tunnel), a file with no decodable audio, and a
    silent one. Also rejects a copy of a known fallback track, so a route that
    politely hands back the default cannot be mistaken for the real thing.
    """
    try:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return False
    except OSError:
        return False
    if fingerprints and fallback_audio.is_fallback(path, fingerprints):
        return False
    if sources.inspect_audio is None:
        return True
    try:
        facts = sources.inspect_audio(path)
    except Exception:
        return False
    return facts.duration_s > 0 and not facts.silent


def _attempt(name, path, fetch, sources, fingerprints):
    """Run one route into ``path``; True only when it produced usable audio."""
    try:
        if not fetch():
            return False
    except Exception as error:
        logging.debug("slideshow audio route %s failed: %s", name, error)
        return False
    if is_usable(path, sources, fingerprints):
        return True
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    return False


def fetch_original(link, destination, sources, picker_audio_url=None, fingerprints=()):
    """Fetch ``link``'s real soundtrack into ``destination``.

    Returns the name of the route that worked, or ``None`` when every route
    failed — which is the caller's signal that a fallback is being substituted
    and must be recorded as such.
    """
    routes = []
    if picker_audio_url and sources.download_file:
        routes.append(("cobalt-picker", lambda: sources.download_file(picker_audio_url, destination)))
    if sources.resolve_audio and sources.download_file:
        def cobalt_audio_mode():
            url = sources.resolve_audio(link)
            return bool(url) and sources.download_file(url, destination)
        routes.append(("cobalt-audio", cobalt_audio_mode))
    if sources.ytdlp_audio:
        routes.append(("yt-dlp", lambda: sources.ytdlp_audio(link, destination)))

    for name, fetch in routes:
        if _attempt(name, destination, fetch, sources, fingerprints):
            return name
    return None
