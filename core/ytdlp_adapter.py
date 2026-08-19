"""The Archive's narrow yt-dlp adapter for metadata and video fallback."""
import importlib
import os
import re
import shutil
import subprocess
import tempfile
import threading


_POST_ID = re.compile(r"/(?:video|photo)/(\d+)")
_SHARE_ID = re.compile(r"/share/(?:video|photo)/(\d+)")


def _comment_limit_from_environment():
    try:
        return max(0, min(int(os.environ.get("SOURCE_COMMENT_LIMIT", "500")), 5000))
    except ValueError:
        return 500


DEFAULT_COMMENT_LIMIT = _comment_limit_from_environment()
_COMMENT_URL = "https://www.tiktok.com/api/comment/list/"
_REPLY_URL = "https://www.tiktok.com/api/comment/list/reply/"
_HTTP_LOCAL = threading.local()
_YDL_LOCAL = threading.local()


def _comment_request(url, **kwargs):
    session = getattr(_HTTP_LOCAL, "session", None)
    if session is None:
        import requests
        session = requests.Session()
        _HTTP_LOCAL.session = session
    return session.get(url, **kwargs)


def _worker_ydl(ydl_class, options):
    """Reuse yt-dlp's extractor/session state within one pool worker."""
    instances = getattr(_YDL_LOCAL, "instances", None)
    if instances is None:
        instances = {}
        _YDL_LOCAL.instances = instances
    key = (ydl_class, bool(options.get("getcomments")))
    if key not in instances:
        instances[key] = ydl_class(options)
    return instances[key]


_HEADER_MODULES = ("_urllib", "_requests")
_accept_encoding_disabled = False


def _keep_accept_encoding_off(headers, supported_encodings):
    """Stand-in for yt-dlp's header helper that adds nothing."""
    return None


def suppress_accept_encoding():
    """Stop yt-dlp announcing Accept-Encoding, which TikTok now refuses.

    TikTok's edge answers any request carrying that header with a 537-byte
    "Site Maintenance" stub instead of the post page, whatever the value --
    gzip, br, identity, even empty. Omitting it entirely returns the real page.
    yt-dlp adds one automatically in every HTTP handler, and each handler
    imports the helper by name, so the name has to be replaced inside each
    handler module rather than at its definition.

    Impersonation is deliberately left unavailable (no curl_cffi): a browser
    fingerprint always carries Accept-Encoding, so it is refused too.
    """
    global _accept_encoding_disabled
    if _accept_encoding_disabled:
        return
    for name in _HEADER_MODULES:
        try:
            module = importlib.import_module(f"yt_dlp.networking.{name}")
        except ImportError:
            continue  # optional backend, nothing to patch
        if hasattr(module, "add_accept_encoding_header"):
            module.add_accept_encoding_header = _keep_accept_encoding_off
    _accept_encoding_disabled = True


def canonical_post_url(link):
    match = _POST_ID.search(link or "") or _SHARE_ID.search(link or "")
    if match:
        return f"https://www.tiktok.com/@x/video/{match.group(1)}"
    return link


def _comment(raw, parent=None):
    user = raw.get("user") or {}
    parent_value = parent or raw.get("reply_id")
    if parent_value in (None, "", "0", 0):
        parent_value = "root"
    return {
        "id": str(raw.get("cid") or ""),
        "parent": str(parent_value),
        "author": user.get("nickname") or user.get("unique_id") or "",
        "author_id": str(user.get("uid") or user.get("sec_uid") or ""),
        "author_username": user.get("unique_id") or "",
        "text": raw.get("text") or "",
        "timestamp": raw.get("create_time"),
        "like_count": raw.get("digg_count"),
    }


def extract_comments(post_id, requester=None, limit=DEFAULT_COMMENT_LIMIT):
    """Best-effort public TikTok comments, including complete reply threads."""
    if requester is None:
        requester = _comment_request
    limit = max(0, min(int(limit), 5000))
    if limit == 0:
        return []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/147 Safari/537.36",
        "Referer": f"https://www.tiktok.com/@x/video/{post_id}",
    }
    comments = []
    seen = set()

    def append(raw, parent=None):
        comment = _comment(raw, parent=parent)
        if not comment["id"] or comment["id"] in seen or len(comments) >= limit:
            return
        seen.add(comment["id"])
        comments.append(comment)

    cursor = 0
    while len(comments) < limit:
        response = requester(
            _COMMENT_URL,
            params={"aid": "1988", "aweme_id": str(post_id), "count": "50", "cursor": str(cursor)},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        top_level = data.get("comments") or []
        for raw in top_level:
            append(raw)
            parent_id = str(raw.get("cid") or "")
            embedded = raw.get("reply_comment") or []
            for reply in embedded:
                append(reply, parent=parent_id)
            if len(comments) >= limit:
                break
            if int(raw.get("reply_comment_total") or 0) <= len(embedded):
                continue
            reply_cursor = 0
            while len(comments) < limit:
                reply_response = requester(
                    _REPLY_URL,
                    params={
                        "aid": "1988", "comment_id": parent_id,
                        "item_id": str(post_id), "count": "50",
                        "cursor": str(reply_cursor),
                    },
                    headers=headers,
                    timeout=30,
                )
                reply_response.raise_for_status()
                reply_data = reply_response.json()
                for reply in reply_data.get("comments") or []:
                    append(reply, parent=parent_id)
                if not reply_data.get("has_more"):
                    break
                next_cursor = int(reply_data.get("cursor") or 0)
                if next_cursor == reply_cursor:
                    break
                reply_cursor = next_cursor
        if not data.get("has_more") or not top_level:
            break
        next_cursor = int(data.get("cursor") or 0)
        if next_cursor == cursor:
            break
        cursor = next_cursor
    return comments


def extract_post(link, include_comments=True, ydl_class=None):
    use_worker_instance = ydl_class is None
    if ydl_class is None:
        from yt_dlp import YoutubeDL
        suppress_accept_encoding()
        ydl_class = YoutubeDL
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "socket_timeout": 30,
        "retries": 3,
        "getcomments": bool(include_comments),
    }
    if use_worker_instance:
        info = _worker_ydl(ydl_class, options).extract_info(
            canonical_post_url(link), download=False,
        )
    else:
        with ydl_class(options) as ydl:
            info = ydl.extract_info(canonical_post_url(link), download=False)
    if include_comments and info and not info.get("comments") and info.get("id"):
        try:
            info["comments"] = extract_comments(info["id"])
        except Exception:
            # Metadata and media remain valuable when TikTok changes or rate
            # limits its undocumented public comment endpoint. Do not publish
            # a false empty snapshot: leaving this pending makes it retryable.
            info.pop("comments", None)
            info["_comments_attempted"] = False
        else:
            info["_comments_attempted"] = True
    return info


def _fact(facts, name, default=None):
    return facts.get(name, default) if isinstance(facts, dict) else getattr(facts, name, default)


def _durations_are_synced(video_facts, audio_facts):
    video_duration = float(_fact(video_facts, "duration_s", 0) or 0)
    audio_duration = float(_fact(audio_facts, "duration_s", 0) or 0)
    if video_duration <= 0 or audio_duration <= 0:
        return False
    return abs(video_duration - audio_duration) <= max(0.75, video_duration * 0.02)


def _repair_silent_video(video_path, audio_path, output_path, runner):
    """Copy pristine video and mux in the verified audible rendition's audio."""
    runner(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-y",
            "-i", video_path, "-i", audio_path,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "copy", "-shortest",
            "-movflags", "+faststart", output_path,
        ],
        check=True,
        capture_output=True,
    )


def download_best_video(link, destination, ydl_class=None, inspect=None,
                        runner=subprocess.run):
    """Publish the best audible rendition, repairing a synced silent HD copy."""
    if ydl_class is None:
        from yt_dlp import YoutubeDL
        suppress_accept_encoding()
        ydl_class = YoutubeDL
    if inspect is None:
        from core.media_index import inspect_media
        inspect = inspect_media
    parent = os.path.dirname(os.path.abspath(destination))
    os.makedirs(parent, exist_ok=True)
    temporary_dir = tempfile.mkdtemp(prefix="ytdlp-", dir=parent)
    try:
        selectors = (
            "best[ext=mp4][vcodec!=none][acodec!=none]/best[vcodec!=none][acodec!=none]",
            "best[height<=720][vcodec!=none][acodec!=none]",
            "best[height<=540][vcodec!=none][acodec!=none]",
            "best[height<=360][vcodec!=none][acodec!=none]",
            "best[ext=mp4][vcodec=h264][vcodec!=none]/best[vcodec=h264][vcodec!=none]",
            "download",
        )
        chosen = None
        chosen_rank = None
        inspected = []

        for index, selector in enumerate(selectors):
            template = os.path.join(temporary_dir, f"candidate-{index}.%(ext)s")
            options = {
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "outtmpl": template,
                "format": selector,
                "merge_output_format": "mp4",
                "socket_timeout": 30,
                "retries": 3,
                "continuedl": True,
                "noplaylist": True,
            }
            try:
                with ydl_class(options) as ydl:
                    ydl.download([canonical_post_url(link)])
            except Exception:
                continue
            candidates = [
                os.path.join(temporary_dir, name)
                for name in os.listdir(temporary_dir)
                if name.startswith(f"candidate-{index}.")
                and not name.endswith((".part", ".ytdl"))
                and os.path.isfile(os.path.join(temporary_dir, name))
            ]
            if not candidates:
                continue
            candidate = max(candidates, key=os.path.getsize)
            try:
                facts = inspect(candidate)
                audible = bool(_fact(facts, "has_audio", True)) and not bool(
                    _fact(facts, "audio_silent", False)
                )
                pixels = int(_fact(facts, "width", 0) or 0) * int(_fact(facts, "height", 0) or 0)
                rank = (1 if audible else 0, pixels, os.path.getsize(candidate))
                inspected.append((candidate, facts, audible, pixels))
            except Exception:
                # If ffprobe is unavailable, retain yt-dlp's own first choice.
                chosen = candidate
                break
            if chosen_rank is None or rank > chosen_rank:
                chosen, chosen_rank = candidate, rank
            if audible:
                break
        audible_candidates = [entry for entry in inspected if entry[2]]
        silent_candidates = [entry for entry in inspected if not entry[2]]
        if audible_candidates and silent_candidates:
            audible = max(audible_candidates, key=lambda entry: (entry[3], os.path.getsize(entry[0])))
            silent = max(silent_candidates, key=lambda entry: (entry[3], os.path.getsize(entry[0])))
            if silent[3] > audible[3] and _durations_are_synced(silent[1], audible[1]):
                repaired = os.path.join(temporary_dir, "candidate-repaired.mp4")
                try:
                    _repair_silent_video(silent[0], audible[0], repaired, runner)
                    repaired_facts = inspect(repaired)
                    repaired_audible = bool(_fact(repaired_facts, "has_audio", True)) and not bool(
                        _fact(repaired_facts, "audio_silent", False)
                    )
                    repaired_pixels = int(_fact(repaired_facts, "width", 0) or 0) * int(
                        _fact(repaired_facts, "height", 0) or 0
                    )
                    if repaired_audible and repaired_pixels >= silent[3]:
                        chosen = repaired
                except Exception:
                    # A/V timestamps or codecs may be incompatible. The verified
                    # audible candidate remains the safe fallback.
                    pass
        if chosen is None:
            return False
        os.replace(chosen, destination)
        return os.path.getsize(destination) > 0
    except Exception:
        return False
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)


def download_audio(link, destination, ydl_class=None):
    """Download the post's audio-only rendition to ``destination`` as MP3.

    The route that does not involve Cobalt at all: TikTok exposes a photo post's
    soundtrack as a plain audio format, so this works for slideshows, whose
    sound Cobalt's passthrough tunnel is unreliable about.
    """
    if ydl_class is None:
        from yt_dlp import YoutubeDL
        suppress_accept_encoding()
        ydl_class = YoutubeDL
    parent = os.path.dirname(os.path.abspath(destination))
    os.makedirs(parent, exist_ok=True)
    temporary_dir = tempfile.mkdtemp(prefix="ytdlp-audio-", dir=parent)
    try:
        options = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "outtmpl": os.path.join(temporary_dir, "audio.%(ext)s"),
            "format": "bestaudio/best",
            "socket_timeout": 30,
            "retries": 3,
            "noplaylist": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }],
        }
        try:
            with ydl_class(options) as ydl:
                ydl.download([canonical_post_url(link)])
        except Exception:
            return False
        produced = [
            os.path.join(temporary_dir, name)
            for name in os.listdir(temporary_dir)
            if not name.endswith((".part", ".ytdl"))
            and os.path.isfile(os.path.join(temporary_dir, name))
        ]
        if not produced:
            return False
        # Prefer the transcoded MP3; fall back to whatever single file remains
        # when FFmpeg post-processing was unavailable.
        chosen = next(
            (path for path in produced if path.lower().endswith(".mp3")),
            max(produced, key=os.path.getsize),
        )
        os.replace(chosen, destination)
        return os.path.getsize(destination) > 0
    except Exception:
        return False
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)


# Placeholder music titles TikTok reports when a post carries no real track
# (an original recording, or a creator's own voice). Treating these as an
# identified song would be the same mistake as trusting the fallback audio.
_NON_TRACK_TITLES = frozenset({
    "original sound", "originalton", "son original", "sonido original",
    "suono originale", "оригинальный звук", "original audio",
})


def extract_track(link, info=None, ydl_class=None):
    """The post's own music credit from TikTok, or ``None``.

    TikTok names the sound a post uses, so for the many favorites that use a
    catalogued track this is an exact answer that needs no acoustic matching at
    all. Returns ``{"title", "artist", "album"}``; a creator's own audio (which
    TikTok labels "original sound") is reported as no track rather than as a
    song called "original sound".
    """
    if info is None:
        info = extract_post(link, include_comments=False, ydl_class=ydl_class)
    if not info:
        return None
    title = (info.get("track") or "").strip()
    artist = (info.get("artist") or "").strip()
    if not title or title.lower() in _NON_TRACK_TITLES:
        return None
    return {
        "title": title,
        "artist": artist or None,
        "album": (info.get("album") or "").strip() or None,
    }
