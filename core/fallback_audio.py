"""Recognising a slideshow soundtrack that is really the fallback track.

When a slideshow's own sound cannot be fetched, the encoder still needs *some*
audio, so a default track is substituted. Once written to ``<n>/audio.mp3`` that
substitute is byte-identical across every affected favorite and otherwise
indistinguishable from a real soundtrack — which is how a single fallback song
ends up "identified" hundreds of times and dominating the library's music
statistics.

This module makes the substitute recognisable again. A fallback is identified by
the SHA-1 of its bytes:

* every default track this project has ever shipped (``SHIPPED_DEFAULTS``), so an
  archive built across a version that swapped the bundled track is still fully
  classifiable — the old track is gone from disk but its fingerprint is not;
* whatever ``config.DEFAULT_AUDIO`` and the user's custom default resolve to
  right now, hashed live, which covers a default we have never seen;
* any fingerprint the caller has separately confirmed (see ``repeated``).

Standard library only, so it stays unit-testable without media tooling.
"""
import hashlib
import os

from core import config, layout

# Every default slideshow track this project has bundled, by SHA-1 of the file.
#
# The bundled track has been swapped over the project's life, so an archive
# assembled across that change contains more than one fallback — recognising
# only the *current* default would silently leave the earlier one classified as
# real audio. These fingerprints are permanent history: keep old entries when
# adding a new one.
SHIPPED_DEFAULTS = {
    "53e820c34704a9ee0ca9b270d1de48bc50485cb5",  # v1 bundled default.mp3 (952156 B)
    "fe3b5ac0fc3fb5f4c8eee2908a554b2272dc8fe7",  # v2 bundled default.mp3 (971380 B)
    "115dfb12be6d879dc1f0e4111a7381c799e40dd2",  # v3 bundled default.mp3 (15442755 B)
}

# How many favorites must share one soundtrack before ``repeated`` reports it.
# Two posts legitimately sharing a sound download byte-identical audio, so a
# small cluster proves nothing; a large one is a substitution, not a trend.
REPEAT_THRESHOLD = 5

_CHUNK = 1024 * 256


def fingerprint(path):
    """SHA-1 of the file at ``path``, or ``None`` when it is not readable."""
    try:
        digest = hashlib.sha1()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def live_defaults(download_dir, default_audio=None, custom_name=None):
    """Fingerprints of the default tracks present on this machine right now.

    Covers a bundled or user-uploaded default whose fingerprint predates (or
    never reaches) ``SHIPPED_DEFAULTS``.
    """
    candidates = [default_audio or config.DEFAULT_AUDIO]
    if download_dir:
        candidates.append(layout.custom_default_audio(download_dir))
        if custom_name:
            candidates.append(os.path.join(download_dir, layout.ARCHIVE_DIR, custom_name))
    found = set()
    for path in candidates:
        if path and os.path.isfile(path):
            digest = fingerprint(path)
            if digest:
                found.add(digest)
    return found


def known(download_dir=None, extra=(), default_audio=None, custom_name=None):
    """Every fingerprint that means "this is the fallback, not the real sound"."""
    return set(SHIPPED_DEFAULTS) | live_defaults(
        download_dir, default_audio=default_audio, custom_name=custom_name,
    ) | {digest for digest in extra if digest}


def is_fallback(path, fingerprints):
    """Whether the audio file at ``path`` is one of the known fallback tracks.

    A missing or unreadable file is not a fallback — it is an absence, which the
    caller handles as its own (also repairable) case.
    """
    digest = fingerprint(path)
    return digest is not None and digest in fingerprints


def repeated(fingerprints_by_item, threshold=REPEAT_THRESHOLD, known_fingerprints=()):
    """Fingerprints shared by at least ``threshold`` favorites, minus known ones.

    A substitution that this build has no record of — an older custom default the
    user has since deleted, say — still betrays itself by being byte-identical
    across unrelated posts. Returns ``{fingerprint: [item_id, ...]}`` so the
    caller can show the evidence and decide, rather than deleting audio on a
    guess.
    """
    clusters = {}
    for item_id, digest in fingerprints_by_item.items():
        if digest:
            clusters.setdefault(digest, []).append(item_id)
    return {
        digest: sorted(ids)
        for digest, ids in clusters.items()
        if len(ids) >= threshold and digest not in set(known_fingerprints)
    }
