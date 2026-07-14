"""Song identification backend (Shazam, via the ``shazamio`` library).

The Shazam catalog has no official API, so we use ``shazamio`` — a free,
reverse-engineered client. This is the one feature that sends data off the
machine: a short audio clip is uploaded to Shazam's servers. It is opt-in and
gated by the caller.

``shazamio`` is async and ships a Rust core, so it is imported lazily inside
``recognize`` and ``search``. The response parsers below stay import-free and
pure, so they are unit-testable without the dependency or a network.
"""
import re
from collections import namedtuple

SongMatch = namedtuple(
    "SongMatch",
    "key title artist album art_url shazam_url apple_url spotify_url",
    defaults=(None, None, None, None, None, None),
)


def _section_album(track):
    """Pull the album name out of Shazam's ``sections`` metadata, if present."""
    for section in track.get("sections") or []:
        if section.get("type") != "SONG":
            continue
        for entry in section.get("metadata") or []:
            if (entry.get("title") or "").lower() == "album":
                return entry.get("text") or None
    return None


def _provider_url(track, *names):
    """Best-effort direct streaming URL for a provider (Apple Music / Spotify).

    Shazam nests provider links in its ``hub`` block; the shape varies, so we
    scan providers/options and return the first action URI whose provider name
    matches. Returns ``None`` when that provider is absent (the UI then falls
    back to a text search link).
    """
    hub = track.get("hub") or {}
    wanted = {name.lower() for name in names}
    for group in list(hub.get("providers") or []) + list(hub.get("options") or []):
        label = f"{group.get('caption') or ''} {group.get('type') or ''}".lower()
        for action in group.get("actions") or []:
            uri = action.get("uri") or action.get("href")
            if not uri:
                continue
            haystack = f"{label} {uri}".lower()
            if any(name in haystack for name in wanted):
                return uri
    return None


def _track_to_match(track):
    """Convert one Shazam ``track`` object into a SongMatch (or None if empty)."""
    if not track:
        return None
    title = track.get("title")
    if not title:
        return None
    return SongMatch(
        key=track.get("key"),
        title=title,
        artist=track.get("subtitle"),
        album=_section_album(track),
        art_url=(track.get("images") or {}).get("coverart"),
        shazam_url=track.get("url"),
        apple_url=_provider_url(track, "applemusic", "apple music", "itunes"),
        spotify_url=_provider_url(track, "spotify"),
    )


def build_recognition(raw):
    """Parse a Shazam ``recognize`` response into a SongMatch, or None.

    None means no confident match (empty ``matches``). Pure — safe to unit test
    with a captured payload.
    """
    if not raw or not raw.get("matches"):
        return None
    return _track_to_match(raw.get("track") or {})


def build_search_results(raw, limit=None):
    """Parse a Shazam ``search_track`` response into candidate SongMatches."""
    hits = ((raw or {}).get("tracks") or {}).get("hits") or []
    matches = []
    for hit in hits:
        match = _track_to_match(hit.get("track") or {})
        if match:
            matches.append(match)
        if limit and len(matches) >= limit:
            break
    return matches


_WS = re.compile(r"\s+")


def dedup_key(match):
    """A stable identity so many favorites collapse onto one song row.

    Shazam's track key when present; otherwise a normalized title+artist.
    """
    if match.key:
        return f"shazam:{match.key}"
    title = _WS.sub(" ", (match.title or "").strip().lower())
    artist = _WS.sub(" ", (match.artist or "").strip().lower())
    return f"ta:{title}|{artist}"


def recognize(clip_path):  # pragma: no cover - network + native dependency
    """Identify the song in an audio file via Shazam; SongMatch or None.

    Sends ``clip_path`` to Shazam's servers. Lazy-imports shazamio so this
    module (and its parsers) load without the dependency installed.
    """
    import asyncio
    from shazamio import Shazam

    async def _run():
        return await Shazam().recognize(clip_path)

    return build_recognition(asyncio.run(_run()))


def search(query, limit=8):  # pragma: no cover - network + native dependency
    """Search Shazam's catalog by text for the manual 'match it myself' flow."""
    import asyncio
    from shazamio import Shazam

    async def _run():
        return await Shazam().search_track(query=query, limit=limit)

    return build_search_results(asyncio.run(_run()), limit=limit)
