"""Recover the real soundtrack of slideshows that were archived with a default.

Slideshows whose sound could not be fetched were archived with a substituted
default track and no record that a substitution had happened. This run repairs
that history in three steps per favorite:

* **classify** — hash the stored ``<n>/audio.mp3`` against every default track
  this project has shipped (and the user's own), so a substitution is
  recognisable even when it came from a default that has since been replaced;
* **refetch** — try the independent routes in ``slideshow_audio`` to get the
  post's real sound, and rebuild the MP4 around it when one succeeds;
* **un-skew** — clear any song "identified" from a substituted track, because
  that conclusion described the default, not the favorite.

Classification alone is worth running: even where the sound is gone for good
(deleted posts), marking the favorite stops the default track being counted as
its music forever after.

Every backend is injected, so the whole pass is testable without Cobalt, yt-dlp,
ffmpeg, or a network.
"""
import logging
import os
import shutil
import tempfile

from core import (
    fallback_audio, layout, media_index, slideshow, slideshow_audio, store,
)


def _classify(path, fingerprints):
    """What the stored soundtrack at ``path`` is: original, fallback, or absent."""
    if not os.path.isfile(path):
        return None
    return (
        slideshow_audio.FALLBACK
        if fallback_audio.is_fallback(path, fingerprints)
        else slideshow_audio.ORIGINAL
    )


def _reencode(download_dir, item_id, audio, encoder):
    """Rebuild the favorite's MP4 around its recovered soundtrack.

    The raw images on disk are the same ones the original encode used, so the
    rebuilt movie differs only in its sound.
    """
    assets = layout.assets_dir(download_dir, item_id)
    images = [
        os.path.join(assets, name)
        for name in layout.slideshow_images(download_dir, item_id)
    ]
    if not images:
        return False
    return bool(encoder(images, audio, layout.movie(download_dir, item_id)))


def _reindex(conn, download_dir, item_id, inspect):
    """Refresh the stored media facts after the movie was rebuilt."""
    movie = layout.movie(download_dir, item_id)
    if inspect is None or not os.path.isfile(movie):
        return
    try:
        facts = inspect(movie)
    except Exception:
        return
    row = store.get_item(conn, item_id)
    thumbnail = row["thumbnail_path"] if row is not None else None
    store.record_media_index(
        conn, item_id, facts.to_index(thumbnail)._asdict(),
        media_index.file_fingerprint(movie),
    )


def repair_item(conn, download_dir, item, fingerprints, sources, encoder=None,
                inspect=None, refetch=True):
    """Repair one favorite's soundtrack. Returns the outcome name.

    ``'kept'`` the stored audio was already the post's own sound;
    ``'recovered'`` the real sound was fetched and the movie rebuilt;
    ``'unavailable'`` no route could produce it, so it stays marked as a
    substitute; ``'skipped'`` there was nothing on disk to work with.
    """
    item_id = item["id"]
    stored = layout.slideshow_audio(download_dir, item_id)
    state = _classify(stored, fingerprints)

    if state == slideshow_audio.ORIGINAL:
        store.set_audio_source(conn, item_id, slideshow_audio.ORIGINAL)
        return "kept"
    if state is None and not layout.slideshow_images(download_dir, item_id):
        return "skipped"

    # From here the favorite is known to be carrying a substitute (or nothing).
    # Record that first: if the refetch fails, or the run is stopped, the
    # archive is still left honest about what it holds.
    store.set_audio_source(conn, item_id, slideshow_audio.FALLBACK)
    store.reset_song_identification(conn, [item_id])
    if not refetch:
        return "unavailable"

    work = tempfile.mkdtemp(prefix="audio_repair_")
    try:
        candidate = os.path.join(work, "audio.mp3")
        route = slideshow_audio.fetch_original(
            item["link"], candidate, sources, fingerprints=fingerprints,
        )
        if not route:
            return "unavailable"
        if encoder is not None and not _reencode(download_dir, item_id, candidate, encoder):
            # The movie is what plays in the Gallery and what song
            # identification reads. Publishing the audio without it would leave
            # the two disagreeing, so treat a failed rebuild as a failed repair.
            logging.warning("could not rebuild slideshow %s around its recovered audio", item_id)
            return "unavailable"
        os.makedirs(os.path.dirname(stored), exist_ok=True)
        shutil.copy(candidate, stored)
        store.set_audio_source(conn, item_id, slideshow_audio.ORIGINAL)
        _reindex(conn, download_dir, item_id, inspect)
        return "recovered"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_slideshow_audio_repair(conn, download_dir, progress=None, should_continue=None,
                               sources=None, encoder=None, inspect=None, control=None,
                               item_ids=None, refetch=True):
    """Repair substituted slideshow soundtracks as a pausable Archive run."""
    from core import runs
    if control is None:
        control = runs.RunControl(conn, progress=progress, wait=None)
    if sources is None and refetch:
        sources = slideshow_audio.build_sources()
    if encoder is None and refetch:
        encoder = slideshow.create_slideshow
    if inspect is None:
        inspect = media_index.inspect_media

    settings = store.get_library_settings(conn)
    fingerprints = fallback_audio.known(
        download_dir, custom_name=settings["default_audio_name"],
    )

    items = store.items_with_assets(conn)
    if item_ids is not None:
        wanted = {int(value) for value in item_ids}
        items = [item for item in items if item["id"] in wanted]

    result = {"completed": 0, "total": len(items), "recovered": 0,
              "kept": 0, "unavailable": 0, "skipped": 0}
    control.progress({"event": "slideshow-audio", **result})

    for item in items:
        if not control.should_continue():
            break
        try:
            outcome = repair_item(
                conn, download_dir, item, fingerprints, sources,
                encoder=encoder, inspect=inspect, refetch=refetch,
            )
        except Exception:
            logging.exception("slideshow audio repair failed for item %s", item["id"])
            outcome = "unavailable"
        result[outcome] += 1
        result["completed"] += 1
        control.progress({"event": "slideshow-audio", "id": item["id"],
                          "outcome": outcome, **result})

    # A cleared identification usually empties the song it pointed at; drop the
    # now-unused rows so the Music view stops listing tracks nothing uses.
    result["songs_pruned"] = store.prune_unused_songs(conn)
    # Anything still shared by many favorites is a default we have no
    # fingerprint for. Report it so it can be confirmed and registered, rather
    # than deleting audio on a guess.
    result["unrecognised_repeats"] = {
        digest: len(ids)
        for digest, ids in unknown_repeats(conn, download_dir).items()
    }
    return result


def unknown_repeats(conn, download_dir, threshold=fallback_audio.REPEAT_THRESHOLD):
    """Soundtracks shared by many favorites that we do *not* recognise.

    A default this build has no fingerprint for — an older custom track the user
    has since replaced — still gives itself away by being byte-identical across
    unrelated posts. Reported rather than acted on, because a genuinely popular
    sound looks the same from here and deleting real audio is not undoable.
    """
    settings = store.get_library_settings(conn)
    known = fallback_audio.known(download_dir, custom_name=settings["default_audio_name"])
    digests = {}
    for item in store.items_with_assets(conn):
        path = layout.slideshow_audio(download_dir, item["id"])
        if os.path.isfile(path):
            digests[item["id"]] = fallback_audio.fingerprint(path)
    return fallback_audio.repeated(digests, threshold=threshold, known_fingerprints=known)
