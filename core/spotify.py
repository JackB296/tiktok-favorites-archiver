"""Spotify playlist push (stdlib only): PKCE auth, track matching, playlists.

Everything network-shaped goes through one injected ``http`` callable —
``http(method, url, headers, body) -> (status, parsed_json)`` — so unit tests
never touch the network (the ``core/enrich.py`` seam). Parsers and the match
scorer are pure.

Scope is deliberately minimal: ``playlist-modify-private`` only, and this
module only ever touches playlists it created (their ids are remembered on
``song_playlist.spotify_playlist_id``).
"""
import base64
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

ACCOUNTS_URL = "https://accounts.spotify.com"
API_URL = "https://api.spotify.com/v1"
SCOPE = "playlist-modify-private"

# A candidate below this combined title/artist similarity is not pushed:
# an honestly-unmatched song beats a wrong song in the playlist.
MATCH_THRESHOLD = 0.78


class SpotifyError(Exception):
    """Typed error at this module's seam; the API layer maps it to 4xx/502."""


class TokenExpired(SpotifyError):
    """A 401 mid-run: the access token died early. Refresh once and retry."""


# --- PKCE + URLs (pure given a verifier) ------------------------------------

def generate_verifier():
    return base64.urlsafe_b64encode(os.urandom(64)).rstrip(b"=").decode()


def pkce_challenge(verifier):
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorize_url(client_id, redirect_uri, challenge, state):
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "scope": SCOPE,
        "state": state,
    })
    return f"{ACCOUNTS_URL}/authorize?{params}"


# --- response parsing (pure) -------------------------------------------------

def parse_token_response(data):
    """Token endpoint body -> dict with expires_at stamped from now."""
    if not isinstance(data, dict) or not data.get("access_token"):
        raise SpotifyError("Spotify's token response is missing an access token")
    return {
        "access_token": data["access_token"],
        # Refresh responses may omit refresh_token: keep the old one (caller merges).
        "refresh_token": data.get("refresh_token"),
        "expires_at": int(time.time()) + int(data.get("expires_in") or 3600),
    }


def track_id_from_url(url):
    """A Shazam-stored open.spotify.com track link -> track id, else None.

    Handles the localized form (``/intl-de/track/...``) Shazam sometimes hands out.
    """
    if not url:
        return None
    match = re.search(r"open\.spotify\.com/(?:intl-[a-z]{2}(?:-[A-Z]{2})?/)?track/([A-Za-z0-9]+)", url)
    return match.group(1) if match else None


# --- match scoring (pure) ----------------------------------------------------

_FEAT = re.compile(r"[(\[](?:feat|ft|with)[.\s][^)\]]*[)\]]", re.I)
_JUNK = re.compile(r"[^a-z0-9 ]+")


def _norm(text):
    text = _FEAT.sub(" ", (text or "").lower())
    return " ".join(_JUNK.sub(" ", text).split())


def match_score(title, artist, candidate_title, candidate_artists):
    """0..1 similarity between an identified song and a search candidate."""
    title_score = SequenceMatcher(None, _norm(title), _norm(candidate_title)).ratio()
    if not artist:
        return title_score * 0.9  # title-only matches carry less certainty
    artist_score = max(
        (SequenceMatcher(None, _norm(artist), _norm(a)).ratio() for a in candidate_artists or []),
        default=0.0,
    )
    return 0.65 * title_score + 0.35 * artist_score


def best_match(title, artist, candidates):
    """Highest-scoring candidate at or above the bar, else None.

    Candidates: ``[{id, title, artists: [name, ...], url}, ...]``.
    """
    best = None
    best_score = 0.0
    for candidate in candidates:
        score = match_score(title, artist, candidate.get("title"), candidate.get("artists"))
        if score > best_score:
            best, best_score = candidate, score
    return best if best is not None and best_score >= MATCH_THRESHOLD else None


def parse_search_response(data):
    """Search endpoint body -> match candidates (pure, shape-tolerant)."""
    items = (((data or {}).get("tracks") or {}).get("items")) or []
    candidates = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        candidates.append({
            "id": item["id"],
            "title": item.get("name") or "",
            "artists": [a.get("name") or "" for a in item.get("artists") or []],
            "url": ((item.get("external_urls") or {}).get("spotify")) or f"https://open.spotify.com/track/{item['id']}",
        })
    return candidates


# --- HTTP (default impl; injected everywhere) --------------------------------

def default_http(method, url, headers=None, body=None):
    """stdlib urllib http callable. Returns (status, parsed_json_or_None)."""
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return error.code, None


def _form(fields):
    return urllib.parse.urlencode(fields).encode()


def exchange_code(http, client_id, redirect_uri, code, verifier):
    status, data = http("POST", f"{ACCOUNTS_URL}/api/token",
                        {"Content-Type": "application/x-www-form-urlencoded"},
                        _form({
                            "grant_type": "authorization_code",
                            "code": code,
                            "redirect_uri": redirect_uri,
                            "client_id": client_id,
                            "code_verifier": verifier,
                        }))
    if status != 200:
        raise SpotifyError(_api_error(data, "Spotify rejected the authorization code"))
    return parse_token_response(data)


def refresh_tokens(http, client_id, refresh_token):
    status, data = http("POST", f"{ACCOUNTS_URL}/api/token",
                        {"Content-Type": "application/x-www-form-urlencoded"},
                        _form({
                            "grant_type": "refresh_token",
                            "refresh_token": refresh_token,
                            "client_id": client_id,
                        }))
    if status != 200:
        raise SpotifyError(_api_error(data, "Spotify refused to refresh the session — reconnect your account"))
    tokens = parse_token_response(data)
    if not tokens["refresh_token"]:
        tokens["refresh_token"] = refresh_token
    return tokens


def _api_error(data, fallback):
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return f"{fallback}: {error['message']}"
        if isinstance(error, str):
            description = data.get("error_description")
            return f"{fallback}: {description or error}"
    return fallback


def _bearer(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _check(status, data, fallback):
    if status == 401:
        raise TokenExpired(_api_error(data, "Spotify session expired"))
    if status not in (200, 201):
        raise SpotifyError(_api_error(data, fallback))


def get_account(http, token):
    status, data = http("GET", f"{API_URL}/me", _bearer(token), None)
    _check(status, data, "Could not read the connected Spotify account")
    return {"id": data.get("id"), "name": data.get("display_name") or data.get("id")}


def search_track(http, token, title, artist):
    query = f"track:{title}"
    if artist:
        query += f" artist:{artist}"
    params = urllib.parse.urlencode({"q": query, "type": "track", "limit": 5})
    status, data = http("GET", f"{API_URL}/search?{params}", _bearer(token), None)
    _check(status, data, "Spotify search failed")
    return parse_search_response(data)


def _safe_playlist_url(data, playlist_id):
    """Only trust Spotify's returned link if it's a real open.spotify.com URL;
    otherwise build our own. Keeps a surprising API response from ever putting
    a non-web-link (e.g. a javascript: URL) into a clickable href downstream."""
    url = ((data or {}).get("external_urls") or {}).get("spotify")
    if isinstance(url, str) and url.startswith("https://open.spotify.com/"):
        return url
    return f"https://open.spotify.com/playlist/{playlist_id}"


def create_playlist(http, token, name):
    status, data = http("POST", f"{API_URL}/me/playlists", _bearer(token),
                        json.dumps({"name": name, "public": False,
                                    "description": "Pushed from TikTok Favorites Archive"}).encode())
    _check(status, data, "Could not create the Spotify playlist")
    if not (data or {}).get("id"):
        raise SpotifyError("Could not create the Spotify playlist")
    return {"id": data["id"], "url": _safe_playlist_url(data, data["id"])}


def playlist_exists(http, token, playlist_id):
    status, data = http("GET", f"{API_URL}/playlists/{playlist_id}", _bearer(token), None)
    if status == 401:
        raise TokenExpired(_api_error(data, "Spotify session expired"))
    return status == 200


def replace_playlist_tracks(http, token, playlist_id, track_ids):
    """Replace the playlist's contents. The first chunk PUTs (replace), the
    rest POST (append) — Spotify caps both at 100 uris per request. An empty
    list still PUTs so a re-push mirrors the in-app playlist exactly."""
    uris = [f"spotify:track:{track_id}" for track_id in track_ids]
    chunks = [uris[start:start + 100] for start in range(0, len(uris), 100)] or [[]]
    for index, chunk in enumerate(chunks):
        method = "PUT" if index == 0 else "POST"
        status, data = http(method, f"{API_URL}/playlists/{playlist_id}/tracks",
                            _bearer(token), json.dumps({"uris": chunk}).encode())
        _check(status, data, "Could not update the Spotify playlist")


# --- the push itself ----------------------------------------------------------

def ensure_fresh_token(conn, http, force=False):
    """A usable access token, refreshing when expired (or when forced)."""
    from core import store  # local import: spotify stays importable standalone

    auth = store.get_spotify_auth(conn)
    if auth is None or not auth["refresh_token"] or not auth["client_id"]:
        raise SpotifyError("Spotify is not connected — connect your account in the Music tab first")
    if force or not auth["access_token"] or (auth["expires_at"] or 0) <= time.time() + 60:
        tokens = refresh_tokens(http, auth["client_id"], auth["refresh_token"])
        store.save_spotify_auth(conn, **tokens)
        return tokens["access_token"]
    return auth["access_token"]


def push_playlist(conn, playlist_id, http=None):
    """Push one saved playlist to the connected account. Returns a report.

    A mid-run 401 refreshes once and retries the whole push — the operations
    are idempotent (search, then a full replace), so a retry cannot duplicate.
    """
    http = http or default_http
    try:
        return _push_once(conn, playlist_id, http, force_refresh=False)
    except TokenExpired:
        return _push_once(conn, playlist_id, http, force_refresh=True)


def _push_once(conn, playlist_id, http, force_refresh):
    from core import store

    playlist = store.get_song_playlist(conn, playlist_id)
    if playlist is None:
        raise SpotifyError("That playlist no longer exists")
    token = ensure_fresh_token(conn, http, force=force_refresh)

    track_ids = []
    unmatched = []
    for song_id in playlist["song_ids"]:
        song = store.get_song(conn, song_id)
        if song is None:
            continue  # song rows are never deleted today; guard anyway
        track_id = track_id_from_url(song["spotify_url"])
        if track_id is None:
            candidates = search_track(http, token, song["title"], song["artist"])
            match = best_match(song["title"], song["artist"], candidates)
            if match is None:
                unmatched.append({"title": song["title"], "artist": song["artist"]})
                continue
            track_id = match["id"]
            store.set_song_spotify_url(conn, song_id, match["url"])
        if track_id not in track_ids:  # two songs can resolve to one track
            track_ids.append(track_id)

    created = False
    remote_id = playlist["spotify_playlist_id"]
    if remote_id and playlist_exists(http, token, remote_id):
        url = f"https://open.spotify.com/playlist/{remote_id}"
    else:
        remote = create_playlist(http, token, playlist["name"])
        remote_id, url = remote["id"], remote["url"]
        store.set_song_playlist_spotify_id(conn, playlist_id, remote_id)
        created = True
    replace_playlist_tracks(http, token, remote_id, track_ids)
    return {
        "playlist": playlist["name"],
        "url": url,
        "created": created,
        "pushed": len(track_ids),
        "unmatched": unmatched,
    }
