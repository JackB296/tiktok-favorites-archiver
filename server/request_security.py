"""Loopback Host and browser-intent policy for the local web app."""
from urllib.parse import urlsplit


REQUEST_HEADER = "X-Archive-Request"
REQUEST_MARKER = "1"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DEFAULT_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _host_and_port(authority, scheme):
    if not isinstance(authority, str) or not authority:
        return None
    try:
        parsed = urlsplit(f"//{authority}")
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if hostname is None or parsed.username is not None or parsed.password is not None:
        return None
    if parsed.path or parsed.query or parsed.fragment:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return hostname.lower(), port


def _origin(origin):
    if not isinstance(origin, str) or not origin or origin == "null":
        return None
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or parsed.hostname is None:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return None
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname.lower(), port


class LocalRequestPolicy:
    """Keep every request local and prove browser intent for writes."""

    def __init__(self, allowed_hosts=DEFAULT_ALLOWED_HOSTS):
        self.allowed_hosts = frozenset(host.lower() for host in allowed_hosts)

    def allows(self, method, scheme, host, origin, marker):
        request_host = _host_and_port(host, scheme)
        if request_host is None or request_host[0] not in self.allowed_hosts:
            return False
        if str(method).upper() in SAFE_METHODS:
            return True
        if marker == REQUEST_MARKER:
            return True
        request_origin = _origin(origin)
        if request_origin is None:
            return False
        return request_origin == (scheme, request_host[0], request_host[1])
