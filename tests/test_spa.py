"""Tests for the SPA deep-link fallback decision (stdlib only)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import spa


def test_client_routes_fall_back_to_the_app_shell():
    for path in ("gallery", "/gallery", "sync", "gallery/anything", "settings"):
        assert spa.is_client_route(path), path


def test_reserved_api_and_media_paths_keep_their_404s():
    for path in ("api", "api/unknown", "/api/items/999999", "media", "media/missing.mp4", "API/unknown", "Media/x"):
        assert not spa.is_client_route(path), path


def test_missing_static_assets_keep_their_404s():
    for path in ("assets/missing.js", "assets/missing.css", "favicon.ico", "robots.txt", "image.webp"):
        assert not spa.is_client_route(path), path


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
