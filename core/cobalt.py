"""Cobalt API client: payload, resolve(), client-side rate limiting, 429 backoff.

``requests`` is imported lazily inside the functions that actually make HTTP
calls, so this module — and its pure logic (``parse_response``, ``RateLimiter``)
— imports with the standard library alone and stays unit-testable without any
third-party install.
"""
import json
import time
import logging
import threading
from collections import deque, namedtuple

from core import config

# A resolved link. ``kind`` is one of: 'video', 'slideshow', 'error',
# 'unsupported', 'unknown'.
Result = namedtuple("Result", "kind url images audio error status")


def _result(kind, url=None, images=None, audio=None, error=None, status=None):
    return Result(kind, url, images, audio, error, status)


def create_payload(url):
    return {
        "url": url,
        "videoQuality": "max",
        "allowH265": True,
        "audioFormat": "best",
        "tiktokFullAudio": True,
    }


def parse_response(data):
    """Map a Cobalt 200 JSON body to a Result (pure; no I/O)."""
    status = data.get("status")
    if status in ("redirect", "tunnel"):
        url = data.get("url")
        if url:
            return _result("video", url=url, status=status)
        return _result("error", error="no download url in response", status=status)
    if status == "picker":
        picker = data.get("picker") or []
        if picker and picker[0].get("type") == "photo":
            images = [item.get("url") for item in picker if item.get("url")]
            return _result("slideshow", images=images, audio=data.get("audio"), status=status)
        return _result("unsupported", error="picker contains unsupported media", status=status)
    if status == "error":
        return _result("error", error=data.get("error"), status=status)
    return _result("unknown", error=f"unknown status: {status}", status=status)


class RateLimiter:
    """Thread-safe sliding-window limiter: at most ``max_calls`` per ``period`` s.

    ``now``/``sleep`` are injectable so timing is deterministic in tests.
    """

    def __init__(self, max_calls, period=1.0, now=time.monotonic, sleep=time.sleep):
        self.max_calls = max(1, int(max_calls))
        self.period = float(period)
        self._now = now
        self._sleep = sleep
        self._calls = deque()
        self._lock = threading.Lock()

    def _evict(self, now):
        while self._calls and now - self._calls[0] >= self.period:
            self._calls.popleft()

    def acquire(self):
        with self._lock:
            now = self._now()
            self._evict(now)
            if len(self._calls) >= self.max_calls:
                wait = self.period - (now - self._calls[0])
                if wait > 0:
                    self._sleep(wait)
                now = self._now()
                self._evict(now)
            self._calls.append(self._now())


def _retry_after_seconds(resp):
    try:
        value = resp.headers.get("Retry-After")
        return float(value) if value else None
    except (AttributeError, ValueError, TypeError):
        return None


def _default_post(link):
    import requests  # lazy: keeps the module importable without requests
    return requests.post(
        config.COBALT_API_URL, headers=config.HEADERS,
        data=json.dumps(create_payload(link)), timeout=config.REQUEST_TIMEOUT,
    )


def resolve(link, poster=None, limiter=None, max_retries=5, base_backoff=1.0, sleep=time.sleep):
    """Resolve a TikTok link via Cobalt into a Result.

    ``poster(link) -> response`` (with ``.status_code``, ``.json()``, ``.headers``)
    is injectable for testing; ``limiter`` gates the request rate; 429 responses
    back off (honoring ``Retry-After`` when present) and retry.
    """
    poster = poster or _default_post
    for attempt in range(max_retries):
        if limiter is not None:
            limiter.acquire()
        try:
            resp = poster(link)
        except Exception as e:  # network error → backoff + retry
            logging.error(f"Cobalt request failed for {link}: {e}")
            sleep(base_backoff * (2 ** attempt))
            continue
        code = resp.status_code
        if code == 429:
            wait = _retry_after_seconds(resp) or base_backoff * (2 ** attempt)
            logging.warning(f"Cobalt rate limited (429) for {link}; backing off {wait:.1f}s")
            sleep(wait)
            continue
        if code == 200:
            try:
                return parse_response(resp.json())
            except Exception as e:
                return _result("transient", error=f"bad JSON from Cobalt: {e}")
        return _result("transient", error=f"HTTP {code}", status=str(code))
    return _result("transient", error="rate limited (max retries exceeded)")


def check_cobalt(url):
    import requests  # lazy
    try:
        resp = requests.get(url, headers=config.HEADERS, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Cannot reach Cobalt at {url}: {e}")
        return False
