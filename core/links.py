"""What counts as an archivable TikTok link (stdlib only).

Every link that can reach yt-dlp or Cobalt must pass ``is_tiktok_link``; a
hostile export could otherwise point the resolver at an internal host.
"""
from urllib.parse import urlsplit

_TIKTOK_SUFFIXES = (".tiktok.com", ".tiktokv.com")
_TIKTOK_HOSTS = frozenset({"tiktok.com", "tiktokv.com"})


def is_tiktok_link(link):
    if not isinstance(link, str):
        return False
    try:
        parts = urlsplit(link.strip())
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return host in _TIKTOK_HOSTS or host.endswith(_TIKTOK_SUFFIXES)
