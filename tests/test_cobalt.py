"""Tests for core.cobalt — parse_response, RateLimiter, resolve() backoff.

Pure logic + injected poster/clock, so no `requests` install is needed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cobalt


class FakeResp:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


def _poster_from(queue):
    """Return a poster that yields queued responses (or raises if the item is an Exception)."""
    it = iter(queue)

    def poster(link):
        item = next(it)
        if isinstance(item, Exception):
            raise item
        return item
    return poster


def test_parse_video():
    r = cobalt.parse_response({"status": "tunnel", "url": "http://x/v.mp4"})
    assert r.kind == "video" and r.url == "http://x/v.mp4"
    assert cobalt.parse_response({"status": "redirect"}).kind == "error"  # no url


def test_parse_slideshow():
    r = cobalt.parse_response({
        "status": "picker",
        "audio": "http://x/a.mp3",
        "picker": [{"type": "photo", "url": "http://x/1.jpg"},
                   {"type": "photo", "url": "http://x/2.jpg"}],
    })
    assert r.kind == "slideshow" and r.images == ["http://x/1.jpg", "http://x/2.jpg"]
    assert r.audio == "http://x/a.mp3"


def test_parse_unsupported_and_error_and_unknown():
    assert cobalt.parse_response({"status": "picker", "picker": [{"type": "video"}]}).kind == "unsupported"
    assert cobalt.parse_response({"status": "error", "error": {"code": "x"}}).kind == "error"
    assert cobalt.parse_response({"status": "weird"}).kind == "unknown"


def test_rate_limiter_waits_when_over_budget():
    clock = {"t": 0.0}
    slept = []

    def now():
        return clock["t"]

    def sleep(s):
        slept.append(s)
        clock["t"] += s

    rl = cobalt.RateLimiter(max_calls=2, period=10, now=now, sleep=sleep)
    rl.acquire()  # t=0
    rl.acquire()  # t=0 (2 calls in window)
    rl.acquire()  # over budget -> must wait a full period
    assert slept == [10]


def test_resolve_backs_off_on_429_then_succeeds():
    slept = []
    poster = _poster_from([
        FakeResp(429, headers={"Retry-After": "2"}),
        FakeResp(429),
        FakeResp(200, {"status": "tunnel", "url": "http://x/v.mp4"}),
    ])
    r = cobalt.resolve("link", poster=poster, sleep=slept.append, base_backoff=1.0)
    assert r.kind == "video" and r.url == "http://x/v.mp4"
    assert slept == [2.0, 2.0]  # first honors Retry-After=2; second is base*2**1=2


def test_resolve_network_error_then_success():
    slept = []
    poster = _poster_from([ConnectionError("down"), FakeResp(200, {"status": "error", "error": "x"})])
    r = cobalt.resolve("link", poster=poster, sleep=slept.append)
    assert r.kind == "error" and len(slept) == 1


def test_resolve_gives_up_after_max_retries_of_429():
    slept = []
    poster = _poster_from([FakeResp(429) for _ in range(5)])
    r = cobalt.resolve("link", poster=poster, sleep=slept.append, max_retries=5)
    assert r.kind == "transient" and "max retries" in r.error
    assert len(slept) == 5


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
