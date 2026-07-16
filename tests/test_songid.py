"""Tests for core.songid (pure Shazam-response parsers) and the audio-source policy.

No network and no shazamio/ffmpeg needed: the parsers run on captured payloads
and clip extraction runs against an injected fake runner.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import layout, media_index, songid


# A recognize() response shaped like Shazam's, trimmed to the fields we read.
RECOGNIZED = {
    "matches": [{"id": "40522491"}],
    "track": {
        "key": "40522491",
        "title": "Blinding Lights",
        "subtitle": "The Weeknd",
        "images": {"coverart": "https://img.shazam/cover.jpg"},
        "url": "https://www.shazam.com/track/40522491/blinding-lights",
        "sections": [
            {"type": "SONG", "metadata": [
                {"title": "Album", "text": "After Hours"},
                {"title": "Released", "text": "2019"},
            ]},
            {"type": "LYRICS", "text": ["..."]},
        ],
        "hub": {
            "providers": [
                {"type": "SPOTIFY", "actions": [{"uri": "https://open.spotify.com/track/abc"}]},
            ],
            "options": [
                {"caption": "OPEN IN APPLE MUSIC",
                 "actions": [{"uri": "https://music.apple.com/us/album/x/1?i=2"}]},
            ],
        },
    },
}


def test_build_recognition_extracts_all_fields():
    match = songid.build_recognition(RECOGNIZED)
    assert match is not None
    assert match.key == "40522491"
    assert match.title == "Blinding Lights"
    assert match.artist == "The Weeknd"
    assert match.album == "After Hours"
    assert match.art_url == "https://img.shazam/cover.jpg"
    assert match.shazam_url.endswith("blinding-lights")
    assert "open.spotify.com" in match.spotify_url
    assert "music.apple.com" in match.apple_url


def test_build_recognition_none_when_no_match():
    assert songid.build_recognition({"matches": [], "track": {}}) is None
    assert songid.build_recognition({}) is None
    assert songid.build_recognition(None) is None


def test_build_recognition_survives_sparse_track():
    raw = {"matches": [{"id": "1"}], "track": {"title": "Lonely Sound"}}
    match = songid.build_recognition(raw)
    assert match.title == "Lonely Sound"
    assert match.artist is None
    assert match.album is None
    assert match.spotify_url is None
    assert match.apple_url is None


def test_track_without_title_is_not_a_match():
    raw = {"matches": [{"id": "1"}], "track": {"key": "9", "subtitle": "Someone"}}
    assert songid.build_recognition(raw) is None


def test_build_search_results_returns_candidates_and_respects_limit():
    raw = {"tracks": {"hits": [
        {"track": {"key": "1", "title": "Song One", "subtitle": "A"}},
        {"track": {"key": "2", "title": "Song Two", "subtitle": "B"}},
        {"track": {}},  # empty hit is dropped
        {"track": {"key": "3", "title": "Song Three", "subtitle": "C"}},
    ]}}
    results = songid.build_search_results(raw, limit=2)
    assert [m.title for m in results] == ["Song One", "Song Two"]
    assert songid.build_search_results({}) == []


def test_dedup_key_prefers_shazam_key_else_normalizes_title_artist():
    with_key = songid.SongMatch(key="40522491", title="Blinding Lights", artist="The Weeknd")
    assert songid.dedup_key(with_key) == "shazam:40522491"

    a = songid.SongMatch(key=None, title="  Blinding   Lights ", artist="The Weeknd")
    b = songid.SongMatch(key=None, title="blinding lights", artist="the weeknd")
    assert songid.dedup_key(a) == songid.dedup_key(b) == "ta:blinding lights|the weeknd"


def test_extract_clip_builds_a_short_mono_ffmpeg_command():
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append((cmd, kwargs))

    out = media_index.extract_clip("/x/12.mp4", "/tmp/clip.wav", seconds=5, runner=fake_runner)
    assert out == "/tmp/clip.wav"
    cmd, kwargs = calls[0]
    assert cmd[0] == "ffmpeg"
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "5"
    assert cmd[cmd.index("-i") + 1] == "/x/12.mp4"
    assert cmd[-1] == "/tmp/clip.wav"
    assert cmd[cmd.index("-ac") + 1] == "1"      # mono
    assert kwargs.get("check") is True


def test_source_audio_prefers_slideshow_audio_then_falls_back_to_mp4():
    with tempfile.TemporaryDirectory() as d:
        # No slideshow audio -> the finished MP4.
        assert layout.source_audio(d, 7) == os.path.join(d, "7.mp4")
        # Slideshow soundtrack present -> preferred.
        os.makedirs(os.path.join(d, "7"))
        audio_path = os.path.join(d, "7", "audio.mp3")
        with open(audio_path, "wb") as f:
            f.write(b"\x00")
        assert layout.source_audio(d, 7) == audio_path


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
