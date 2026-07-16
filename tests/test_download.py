"""Tests for core.download — atomic .part streaming and retries (stdlib only).

``core.download`` imports ``requests`` at module load, but the suite runs on a
Python without it, so a minimal stub module is installed first. Each test then
replaces ``download.requests.get``, which works against the stub and against a
real ``requests`` alike.
"""
import os
import sys
import types
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "requests" not in sys.modules:
    _exceptions = types.ModuleType("requests.exceptions")
    for _name in ("ChunkedEncodingError", "ConnectionError", "Timeout", "RequestException", "HTTPError"):
        setattr(_exceptions, _name, type(_name, (Exception,), {}))
    _requests = types.ModuleType("requests")
    _requests.exceptions = _exceptions
    _requests.get = None
    sys.modules["requests"] = _requests
    sys.modules["requests.exceptions"] = _exceptions

from core import config, download

# Retries stay instant by stubbing the sleep seam, NOT config.RETRY_DELAY —
# the code must read the real attribute so a missing constant fails loudly here.
_sleeps = []
download._sleep = _sleeps.append


class _Response:
    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        return iter(self._chunks)

    def close(self):
        self.closed = True


def _serve(*outcomes):
    """Queue per-call outcomes: a list of chunks, or an exception to raise."""
    _sleeps.clear()
    calls = {"count": 0, "responses": []}

    def get(url, stream=True, timeout=None):
        outcome = outcomes[min(calls["count"], len(outcomes) - 1)]
        calls["count"] += 1
        if isinstance(outcome, Exception):
            raise outcome
        response = _Response(outcome)
        calls["responses"].append(response)
        return response

    download.requests.get = get
    return calls


def test_success_publishes_atomically_and_leaves_no_part_file():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "1.mp4")
        calls = _serve([b"video-", b"bytes"])
        assert download.download_file("http://x/v", target) is True
        with open(target, "rb") as f:
            assert f.read() == b"video-bytes"
        assert not os.path.exists(target + ".part")
        assert all(r.closed for r in calls["responses"])


def test_zero_byte_download_is_retried():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "1.mp4")
        calls = _serve([], [b"real"])  # first response streams nothing
        assert download.download_file("http://x/v", target) is True
        assert calls["count"] == 2
        assert os.path.getsize(target) == 4
        # The retry pause read the real config constant (regression guard for
        # the once-missing RETRY_DELAY) and closed the discarded response.
        assert _sleeps == [config.RETRY_DELAY]
        assert calls["responses"][0].closed


def test_retry_delay_is_a_real_nonnegative_number():
    assert isinstance(config.RETRY_DELAY, float)
    assert config.RETRY_DELAY >= 0


def test_connection_error_is_retried_then_succeeds():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "1.mp4")
        calls = _serve(download.ConnectionError("reset"), [b"ok"])
        assert download.download_file("http://x/v", target) is True
        assert calls["count"] == 2
        assert _sleeps == [config.RETRY_DELAY]


def test_persistent_failure_returns_false_and_cleans_up():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "1.mp4")
        _serve(download.Timeout("slow"))
        assert download.download_file("http://x/v", target, max_retries=2) is False
        assert os.listdir(d) == []  # no target, no .part left behind


class _FailingResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.closed = False

    def raise_for_status(self):
        error = download.requests.exceptions.HTTPError("boom")
        error.response = self
        raise error

    def iter_content(self, chunk_size):
        return iter([])

    def close(self):
        self.closed = True


def test_http_5xx_is_retried_but_4xx_is_permanent():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "1.mp4")
        calls = _serve(None)
        responses = [_FailingResponse(503), _Response([b"ok"])]
        download.requests.get = lambda url, stream=True, timeout=None: responses.pop(0)
        assert download.download_file("http://x/v", target) is True
        assert _sleeps == [config.RETRY_DELAY]        # one retry pause for the 503

        _sleeps.clear()
        gone = _FailingResponse(404)
        download.requests.get = lambda url, stream=True, timeout=None: gone
        assert download.download_file("http://x/v", target + "b") is False
        assert _sleeps == []                          # 4xx breaks immediately
        assert gone.closed                            # response still closed


def test_unexpected_error_stops_without_retrying_and_cleans_up():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "1.mp4")
        calls = _serve(ValueError("bad url"))
        assert download.download_file("http://x/v", target) is False
        assert calls["count"] == 1
        assert os.listdir(d) == []


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
