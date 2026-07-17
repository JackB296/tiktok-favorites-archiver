"""Tests for core.spotify — PKCE, parsing, match scoring, and the push flow."""
import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import spotify, store
from core.spotify import SpotifyError


def _db():
    conn = store.connect(":memory:")
    return store.init_db(conn)


def _connect(conn, expires_in=3600):
    store.save_spotify_auth(conn, client_id="cid", access_token="tok",
                            refresh_token="ref", expires_at=int(time.time()) + expires_in,
                            account_name="Owner")


class FakeHttp:
    """Scripted responses keyed by (method, url-prefix)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, headers=None, body=None):
        self.calls.append((method, url, body))
        for (route_method, prefix), response in self.routes:
            if method == route_method and url.startswith(prefix):
                return response(self, method, url, body) if callable(response) else response
        raise AssertionError(f"unexpected request: {method} {url}")


def _search_response(*tracks):
    return (200, {"tracks": {"items": [
        {"id": tid, "name": name, "artists": [{"name": artist}],
         "external_urls": {"spotify": f"https://open.spotify.com/track/{tid}"}}
        for tid, name, artist in tracks
    ]}})


# --- pure pieces -------------------------------------------------------------

def test_pkce_challenge_is_urlsafe_sha256_without_padding():
    challenge = spotify.pkce_challenge("test-verifier")
    assert "=" not in challenge and "+" not in challenge and "/" not in challenge
    assert spotify.pkce_challenge("test-verifier") == challenge  # deterministic
    assert spotify.generate_verifier() != spotify.generate_verifier()


def test_authorize_url_carries_the_pkce_and_scope():
    url = spotify.authorize_url("cid", "http://127.0.0.1:8080/cb", "chal", "st")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["client_id"] == ["cid"]
    assert query["code_challenge"] == ["chal"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["playlist-modify-private"]
    assert query["state"] == ["st"]


def test_track_id_from_url_handles_direct_localized_and_junk_links():
    assert spotify.track_id_from_url("https://open.spotify.com/track/abc123XYZ") == "abc123XYZ"
    assert spotify.track_id_from_url("https://open.spotify.com/intl-de/track/abc?si=x") == "abc"
    assert spotify.track_id_from_url("https://example.com/track/abc") is None
    assert spotify.track_id_from_url(None) is None


def test_match_scoring_accepts_near_matches_and_rejects_wrong_songs():
    near = [{"id": "t1", "title": "Blinding Lights (feat. Nobody)", "artists": ["The Weeknd"], "url": "u"}]
    assert spotify.best_match("Blinding Lights", "The Weeknd", near)["id"] == "t1"

    wrong = [{"id": "t2", "title": "Blinded by the Light", "artists": ["Manfred Mann"], "url": "u"}]
    assert spotify.best_match("Blinding Lights", "The Weeknd", wrong) is None

    # Unmatched beats mismatched: an empty candidate list is simply no match.
    assert spotify.best_match("Anything", "Anyone", []) is None


def test_playlist_url_only_trusts_real_open_spotify_links():
    assert spotify._safe_playlist_url(
        {"external_urls": {"spotify": "https://open.spotify.com/playlist/AB"}}, "AB"
    ) == "https://open.spotify.com/playlist/AB"
    # A surprising/hostile value never reaches an href — fall back to our own.
    for hostile in ({"external_urls": {"spotify": "javascript:alert(1)"}},
                    {"external_urls": {"spotify": "http://evil.example/x"}},
                    {}, None):
        assert spotify._safe_playlist_url(hostile, "XY") == "https://open.spotify.com/playlist/XY"


def test_token_response_parsing_requires_a_token_and_stamps_expiry():
    parsed = spotify.parse_token_response({"access_token": "a", "expires_in": 60})
    assert parsed["access_token"] == "a"
    assert parsed["expires_at"] > time.time()
    try:
        spotify.parse_token_response({"error": "x"})
        raise AssertionError("should reject")
    except SpotifyError:
        pass


# --- push flow ----------------------------------------------------------------

def _playlist_db():
    conn = _db()
    direct = store.upsert_song(conn, "ta:direct|a", "Direct Song", artist="A",
                               spotify_url="https://open.spotify.com/track/DIRECT1")
    searchable = store.upsert_song(conn, "ta:findme|b", "Find Me", artist="B")
    hopeless = store.upsert_song(conn, "ta:ghost|c", "Ghost Track", artist="C")
    playlist_id = store.save_saved_list(conn, "song_playlist", "Road Trip",
                                        {"song_ids": [direct, searchable, hopeless]})
    return conn, playlist_id, searchable


def test_push_matches_creates_and_reports_honestly():
    conn, playlist_id, searchable = _playlist_db()
    _connect(conn)
    http = FakeHttp([
        (("GET", "https://api.spotify.com/v1/search?q=track%3AFind+Me+artist%3AB"),
         _search_response(("FOUND1", "Find Me", "B"))),
        (("GET", "https://api.spotify.com/v1/search"), _search_response()),  # ghost: nothing
        (("POST", "https://api.spotify.com/v1/me/playlists"),
         (201, {"id": "PL1", "external_urls": {"spotify": "https://open.spotify.com/playlist/PL1"}})),
        (("PUT", "https://api.spotify.com/v1/playlists/PL1/tracks"), (201, {})),
    ])

    report = spotify.push_playlist(conn, playlist_id, http=http)

    assert report["created"] is True
    assert report["pushed"] == 2
    assert report["unmatched"] == [{"title": "Ghost Track", "artist": "C"}]
    assert report["url"] == "https://open.spotify.com/playlist/PL1"
    # The replace call carries exactly the matched tracks, in playlist order.
    put = next(c for c in http.calls if c[0] == "PUT")
    assert json.loads(put[2]) == {"uris": ["spotify:track:DIRECT1", "spotify:track:FOUND1"]}
    # Search matches write their link back onto the song row.
    assert store.get_song(conn, searchable)["spotify_url"] == "https://open.spotify.com/track/FOUND1"
    # And the remote playlist id is remembered for re-pushes.
    assert store.get_song_playlist(conn, playlist_id)["spotify_playlist_id"] == "PL1"


def test_repush_replaces_the_same_playlist_without_duplicating():
    conn, playlist_id, _searchable = _playlist_db()
    _connect(conn)
    store.set_song_playlist_spotify_id(conn, playlist_id, "PL9")
    http = FakeHttp([
        (("GET", "https://api.spotify.com/v1/search"), _search_response(("FOUND1", "Find Me", "B"))),
        (("GET", "https://api.spotify.com/v1/playlists/PL9"), (200, {"id": "PL9"})),
        (("PUT", "https://api.spotify.com/v1/playlists/PL9/tracks"), (200, {})),
    ])

    report = spotify.push_playlist(conn, playlist_id, http=http)

    assert report["created"] is False
    assert not any(c[0] == "POST" and c[1].endswith("/me/playlists") for c in http.calls)


def test_deleted_remote_playlist_is_recreated_and_id_updated():
    conn, playlist_id, _searchable = _playlist_db()
    _connect(conn)
    store.set_song_playlist_spotify_id(conn, playlist_id, "GONE")
    http = FakeHttp([
        (("GET", "https://api.spotify.com/v1/search"), _search_response(("FOUND1", "Find Me", "B"))),
        (("GET", "https://api.spotify.com/v1/playlists/GONE"), (404, None)),
        (("POST", "https://api.spotify.com/v1/me/playlists"), (201, {"id": "PL2"})),
        (("PUT", "https://api.spotify.com/v1/playlists/PL2/tracks"), (201, {})),
    ])

    report = spotify.push_playlist(conn, playlist_id, http=http)

    assert report["created"] is True
    assert store.get_song_playlist(conn, playlist_id)["spotify_playlist_id"] == "PL2"


def test_expired_token_refreshes_before_and_mid_run():
    conn, playlist_id, _searchable = _playlist_db()
    _connect(conn, expires_in=-10)  # already expired: refresh up front
    http = FakeHttp([
        (("POST", "https://accounts.spotify.com/api/token"),
         (200, {"access_token": "fresh", "expires_in": 3600})),
        (("GET", "https://api.spotify.com/v1/search"), _search_response()),
        (("POST", "https://api.spotify.com/v1/me/playlists"), (201, {"id": "PL3"})),
        (("PUT", "https://api.spotify.com/v1/playlists/PL3/tracks"), (200, {})),
    ])

    spotify.push_playlist(conn, playlist_id, http=http)

    auth = store.get_spotify_auth(conn)
    assert auth["access_token"] == "fresh"
    assert auth["refresh_token"] == "ref"  # omitted in response: old one kept
    # The refresh happened before any API call.
    assert http.calls[0][1].startswith("https://accounts.spotify.com/api/token")


def test_mid_run_401_refreshes_once_and_retries():
    conn, playlist_id, _searchable = _playlist_db()
    _connect(conn)
    state = {"searches": 0}

    def search(_http, _method, _url, _body):
        state["searches"] += 1
        if state["searches"] == 1:
            return (401, {"error": {"status": 401, "message": "expired"}})
        return _search_response(("FOUND1", "Find Me", "B"))

    http = FakeHttp([
        (("GET", "https://api.spotify.com/v1/search"), search),
        (("POST", "https://accounts.spotify.com/api/token"),
         (200, {"access_token": "fresh2", "expires_in": 3600})),
        (("POST", "https://api.spotify.com/v1/me/playlists"), (201, {"id": "PL4"})),
        (("PUT", "https://api.spotify.com/v1/playlists/PL4/tracks"), (200, {})),
    ])

    report = spotify.push_playlist(conn, playlist_id, http=http)

    assert report["pushed"] == 2
    assert store.get_spotify_auth(conn)["access_token"] == "fresh2"


def test_push_without_a_connection_fails_clearly():
    conn, playlist_id, _searchable = _playlist_db()
    try:
        spotify.push_playlist(conn, playlist_id, http=FakeHttp([]))
        raise AssertionError("should fail")
    except SpotifyError as error:
        assert "not connected" in str(error)


def test_disconnect_clears_tokens_but_keeps_the_client_id():
    conn = _db()
    _connect(conn)
    store.clear_spotify_auth(conn)
    auth = store.get_spotify_auth(conn)
    assert auth["access_token"] is None and auth["refresh_token"] is None
    assert auth["client_id"] == "cid"


def test_upgrading_a_pre_spotify_database_adds_the_column_and_table():
    conn = store.connect(":memory:")
    conn.executescript(
        "CREATE TABLE song_playlist (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
        "song_ids_json TEXT NOT NULL, created_at TEXT NOT NULL);"
    )
    store.init_db(conn)  # must not error; adds spotify_playlist_id + spotify_auth
    conn.execute("INSERT INTO song_playlist (name, song_ids_json, created_at) VALUES ('x', '[1]', 'now')")
    assert store.get_song_playlist(conn, 1)["spotify_playlist_id"] is None
    assert store.get_spotify_auth(conn) is None


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
