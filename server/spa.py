"""Decide when an unmatched request path belongs to the web app.

The SPA is mounted at "/" behind the JSON API and media routes. A deep link
such as ``/gallery?sort=latest`` names a client-side route, not a file, so the
static mount must answer it with the SPA shell (``index.html``) instead of a
404. Paths under the app's reserved prefixes keep their real 404s.
"""

_RESERVED_PREFIXES = ("api", "media")


def is_client_route(path):
    """True when a path that matched no file should serve the SPA shell."""
    normalized = path.lstrip("/")
    first_segment = normalized.split("/", 1)[0]
    if first_segment.lower() in _RESERVED_PREFIXES:
        return False
    # A failed request with a filename extension is an asset request, not a
    # browser-router URL. Returning index.html for it gives broken JS/CSS a
    # misleading 200 response and hides the actual missing file.
    filename = normalized.rsplit("/", 1)[-1]
    return "." not in filename
