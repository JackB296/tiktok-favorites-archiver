"""Tests for recognising and recovering substituted slideshow soundtracks.

Covers the fingerprint registry, the multi-route fetcher, and the repair pass.
Every backend is faked, so no Cobalt, yt-dlp, ffmpeg, or network is involved.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (
    cobalt, fallback_audio, layout, slideshow_audio, slideshow_audio_repair, store,
)


def _write(path, data=b"some audio"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


class FakeSources:
    """Stands in for AudioSources; each route is scripted per test."""

    def __init__(self, routes=(), payload=b"real original audio", inspect=True):
        self._routes = dict(routes)
        self._payload = payload
        self.attempts = []
        self.inspect_audio = self._inspect if inspect else None

    def _succeed(self, name, path):
        self.attempts.append(name)
        if not self._routes.get(name):
            return False
        payload = self._routes[name] if isinstance(self._routes[name], bytes) else self._payload
        _write(path, payload)
        return True

    def download_file(self, url, path):
        name = "cobalt-audio" if url == "audio-mode-url" else "cobalt-picker"
        return self._succeed(name, path)

    def resolve_audio(self, link):
        return "audio-mode-url"

    def ytdlp_audio(self, link, path):
        return self._succeed("yt-dlp", path)

    @staticmethod
    def _inspect(path):
        class Facts:
            duration_s = 12.0
            silent = False
        return Facts()


# --- the fix at the source ---------------------------------------------------

def test_cobalt_asks_for_a_concrete_audio_codec():
    """`audioFormat: "best"` is what made Cobalt hand back an empty tunnel for
    photo posts, so the payload must never request passthrough again."""
    payload = cobalt.create_payload("https://tiktok/photo/1")
    assert payload["audioFormat"] == "mp3"
    assert "downloadMode" not in payload
    assert cobalt.create_payload("x", "audio")["downloadMode"] == "audio"


# --- recognising the fallback ------------------------------------------------

def test_every_shipped_default_stays_recognisable():
    """The bundled track has been swapped, so an archive spans more than one
    default; forgetting the old fingerprints would leave those unclassifiable."""
    assert len(fallback_audio.SHIPPED_DEFAULTS) >= 3
    with tempfile.TemporaryDirectory() as work:
        # 'v1 bundled default.mp3' hashes to the first shipped fingerprint only
        # if the bytes match, so assert the mechanism instead: a file whose
        # digest is registered is a fallback, one whose digest is not is real.
        track = _write(os.path.join(work, "audio.mp3"), b"a default track")
        digest = fallback_audio.fingerprint(track)
        assert fallback_audio.is_fallback(track, {digest})
        assert not fallback_audio.is_fallback(track, {"0" * 40})
        assert not fallback_audio.is_fallback(os.path.join(work, "gone.mp3"), {digest})


def test_known_fingerprints_include_the_live_default_on_disk():
    with tempfile.TemporaryDirectory() as work:
        custom = _write(layout.custom_default_audio(work), b"the user's own track")
        known = fallback_audio.known(work, default_audio=None)
        assert fallback_audio.fingerprint(custom) in known
        assert fallback_audio.SHIPPED_DEFAULTS <= known


def test_repeated_reports_an_unrecognised_default_but_not_a_shared_sound():
    """A default we have no record of still betrays itself by being identical
    across many unrelated posts; two posts sharing a sound proves nothing."""
    digests = {n: "aaa" for n in range(1, 9)}
    digests.update({20: "bbb", 21: "bbb", 30: "ccc"})
    found = fallback_audio.repeated(digests, threshold=5)
    assert list(found) == ["aaa"]
    assert found["aaa"] == list(range(1, 9))
    assert fallback_audio.repeated(digests, threshold=5, known_fingerprints={"aaa"}) == {}


# --- the multi-route fetcher -------------------------------------------------

def test_first_working_route_wins_and_later_routes_are_not_tried():
    sources = FakeSources(routes={"cobalt-picker": True})
    with tempfile.TemporaryDirectory() as work:
        route = slideshow_audio.fetch_original(
            "link", os.path.join(work, "a.mp3"), sources, picker_audio_url="picker-url",
        )
    assert route == "cobalt-picker"
    assert sources.attempts == ["cobalt-picker"]


def test_an_empty_tunnel_falls_through_to_the_independent_routes():
    """The real failure: Cobalt answers 200 with zero bytes. That must not be
    accepted as the post's audio, and must not end the search."""
    sources = FakeSources(routes={"cobalt-picker": b"", "cobalt-audio": True})
    with tempfile.TemporaryDirectory() as work:
        target = os.path.join(work, "a.mp3")
        route = slideshow_audio.fetch_original(
            "link", target, sources, picker_audio_url="picker-url",
        )
        assert os.path.getsize(target) > 0
    assert route == "cobalt-audio"
    assert sources.attempts == ["cobalt-picker", "cobalt-audio"]


def test_a_route_that_returns_the_default_track_is_rejected():
    """A route handing back a copy of the fallback is not a success — accepting
    it is exactly how the archive lost track of what was real."""
    default_bytes = b"the bundled default track"
    sources = FakeSources(routes={"cobalt-picker": default_bytes, "yt-dlp": True})
    with tempfile.TemporaryDirectory() as work:
        target = os.path.join(work, "a.mp3")
        known = {fallback_audio.fingerprint(_write(os.path.join(work, "d.mp3"), default_bytes))}
        route = slideshow_audio.fetch_original(
            "link", target, sources, picker_audio_url="picker-url", fingerprints=known,
        )
    assert route == "yt-dlp"
    assert sources.attempts == ["cobalt-picker", "cobalt-audio", "yt-dlp"]


def test_silent_audio_is_not_a_usable_soundtrack():
    class Silent(FakeSources):
        @staticmethod
        def _inspect(path):
            class Facts:
                duration_s = 12.0
                silent = True
            return Facts()

    sources = Silent(routes={"cobalt-picker": True, "cobalt-audio": True, "yt-dlp": True})
    sources.inspect_audio = Silent._inspect
    with tempfile.TemporaryDirectory() as work:
        route = slideshow_audio.fetch_original(
            "link", os.path.join(work, "a.mp3"), sources, picker_audio_url="p",
        )
    assert route is None


def test_every_route_failing_reports_no_route():
    sources = FakeSources()
    with tempfile.TemporaryDirectory() as work:
        assert slideshow_audio.fetch_original(
            "link", os.path.join(work, "a.mp3"), sources, picker_audio_url="p",
        ) is None
    assert sources.attempts == ["cobalt-picker", "cobalt-audio", "yt-dlp"]


# --- the repair pass ---------------------------------------------------------

def _add_slideshow(conn, work, item_id, audio_bytes, link):
    conn.execute(
        "INSERT INTO item (id, link, kind, status, has_assets, created_at, updated_at) "
        "VALUES (?, ?, 'slideshow', 'done', 1, '2026-01-01', '2026-01-01')",
        (item_id, link),
    )
    conn.commit()
    _write(os.path.join(layout.assets_dir(work, item_id), "01.jpg"), b"image")
    if audio_bytes is not None:
        _write(layout.slideshow_audio(work, item_id), audio_bytes)


def _archive(work, item_id, audio_bytes, link="https://tiktok/photo/1"):
    """A finished slideshow on disk plus its database row."""
    conn = store.init_db(store.connect(os.path.join(work, "db.sqlite")))
    _add_slideshow(conn, work, item_id, audio_bytes, link)
    return conn


def test_repair_recovers_the_real_sound_and_clears_the_wrong_song():
    default_bytes = b"the bundled default track"
    with tempfile.TemporaryDirectory() as work:
        conn = _archive(work, 7, default_bytes)
        song = store.upsert_song(conn, "shazam:1", "Default Track", artist="Nobody")
        store.set_item_song(conn, 7, song)
        known = {fallback_audio.fingerprint(layout.slideshow_audio(work, 7))}
        sources = FakeSources(routes={"cobalt-audio": True})
        encoded = {}

        def encoder(images, audio, out):
            encoded["images"] = len(images)
            _write(out, b"movie")
            return True

        outcome = slideshow_audio_repair.repair_item(
            conn, work, store.get_item(conn, 7), known, sources,
            encoder=encoder, inspect=None,
        )

        row = store.get_item(conn, 7)
        stored = open(layout.slideshow_audio(work, 7), "rb").read()
        conn.close()  # Windows will not delete an open SQLite file

    assert outcome == "recovered"
    assert encoded["images"] == 1
    assert stored == b"real original audio"
    assert row["audio_source"] == "original"
    assert row["song_id"] is None and row["song_status"] is None


def test_repair_leaves_real_audio_alone():
    with tempfile.TemporaryDirectory() as work:
        conn = _archive(work, 8, b"this post's own sound")
        song = store.upsert_song(conn, "shazam:2", "A Real Song")
        store.set_item_song(conn, 8, song)
        sources = FakeSources(routes={"cobalt-audio": True})

        outcome = slideshow_audio_repair.repair_item(
            conn, work, store.get_item(conn, 8), {"0" * 40}, sources,
            encoder=lambda *a: True, inspect=None,
        )
        row = store.get_item(conn, 8)
        conn.close()

    assert outcome == "kept"
    assert row["audio_source"] == "original"
    assert row["song_id"] == song  # a real identification is not disturbed
    assert sources.attempts == []  # nothing was refetched


def test_unrecoverable_audio_stays_marked_so_it_is_never_identified_again():
    """A deleted post's sound is gone for good. Marking it is still the point:
    it stops the default track being counted as this favorite's music."""
    default_bytes = b"the bundled default track"
    with tempfile.TemporaryDirectory() as work:
        conn = _archive(work, 9, default_bytes)
        song = store.upsert_song(conn, "shazam:3", "Default Track")
        store.set_item_song(conn, 9, song)
        known = {fallback_audio.fingerprint(layout.slideshow_audio(work, 9))}

        outcome = slideshow_audio_repair.repair_item(
            conn, work, store.get_item(conn, 9), known, FakeSources(),
            encoder=lambda *a: True, inspect=None,
        )
        row = store.get_item(conn, 9)
        eligible = [item["id"] for item in store.items_needing_identification(conn)]
        conn.close()

    assert outcome == "unavailable"
    assert row["audio_source"] == "fallback"
    assert row["song_id"] is None
    assert 9 not in eligible


def test_a_failed_rebuild_does_not_publish_audio_the_movie_lacks():
    default_bytes = b"the bundled default track"
    with tempfile.TemporaryDirectory() as work:
        conn = _archive(work, 10, default_bytes)
        known = {fallback_audio.fingerprint(layout.slideshow_audio(work, 10))}

        outcome = slideshow_audio_repair.repair_item(
            conn, work, store.get_item(conn, 10), known,
            FakeSources(routes={"cobalt-audio": True}),
            encoder=lambda *a: False, inspect=None,
        )
        stored = open(layout.slideshow_audio(work, 10), "rb").read()
        row = store.get_item(conn, 10)
        conn.close()

    assert outcome == "unavailable"
    assert stored == default_bytes  # untouched; audio and movie stay in step
    assert row["audio_source"] == "fallback"


def test_run_reports_a_tally_and_prunes_songs_nothing_uses_any_more():
    default_bytes = b"the bundled default track"
    with tempfile.TemporaryDirectory() as work:
        conn = _archive(work, 11, default_bytes)
        _add_slideshow(conn, work, 12, b"a genuine soundtrack", "https://tiktok/photo/2")

        orphan = store.upsert_song(conn, "shazam:4", "Default Track")
        store.set_item_song(conn, 11, orphan)
        kept = store.upsert_song(conn, "shazam:5", "A Real Song")
        store.set_item_song(conn, 12, kept)

        # The default here is discovered live from the media folder, exactly as
        # a real archive's custom default would be.
        _write(layout.custom_default_audio(work), default_bytes)
        store.set_default_audio(conn, "default-audio.mp3")

        result = slideshow_audio_repair.run_slideshow_audio_repair(
            conn, work, sources=FakeSources(), encoder=lambda *a: True,
            inspect=None, refetch=True,
        )
        songs = {row["id"] for row in conn.execute("SELECT id FROM song")}
        conn.close()

    assert result["total"] == 2
    assert result["unavailable"] == 1 and result["kept"] == 1
    assert result["songs_pruned"] == 1
    assert result["unrecognised_repeats"] == {}
    assert songs == {kept}


def test_pruning_never_drops_a_song_the_user_saved_to_a_playlist():
    """Playlists hold song ids as JSON, not a foreign key, so nothing in the
    database stops a deliberate save being swept away with the wreckage."""
    with tempfile.TemporaryDirectory() as work:
        conn = store.init_db(store.connect(os.path.join(work, "db.sqlite")))
        orphan = store.upsert_song(conn, "shazam:a", "Nothing Uses This")
        saved = store.upsert_song(conn, "shazam:b", "Saved By Hand")
        store.save_saved_list(conn, "song_playlist", "mine", {"song_ids": [saved]})

        pruned = store.prune_unused_songs(conn)
        remaining = {row["id"] for row in conn.execute("SELECT id FROM song")}
        conn.close()

    assert pruned == 1
    assert remaining == {saved}
    assert orphan not in remaining


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failures += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failures else 0)
