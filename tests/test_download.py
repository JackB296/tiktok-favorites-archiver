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

config.RETRY_DELAY = 0  # keep retry tests instant


class _Response:
    def __init__(self, chunks):
        self._chunks = chunks

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        return iter(self._chunks)


def _serve(*outcomes):
    """Queue per-call outcomes: a list of chunks, or an exception to raise."""
    calls = {"count": 0}

    def get(url, stream=True, timeout=None):
        outcome = outcomes[min(calls["count"], len(outcomes) - 1)]
        calls["count"] += 1
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome)

    download.requests.get = get
    return calls


def test_success_publishes_atomically_and_leaves_no_part_file():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "1.mp4")
        _serve([b"video-", b"bytes"])
        assert download.download_file("http://x/v", target) is True
        with open(target, "rb") as f:
            assert f.read() == b"video-bytes"
        assert not os.path.exists(target + ".part")


def test_zero_byte_download_is_retried():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "1.mp4")
        calls = _serve([], [b"real"])  # first response streams nothing
        assert download.download_file("http://x/v", target) is True
        assert calls["count"] == 2
        assert os.path.getsize(target) == 4


def test_connection_error_is_retried_then_succeeds():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "1.mp4")
        calls = _serve(download.ConnectionError("reset"), [b"ok"])
        assert download.download_file("http://x/v", target) is True
        assert calls["count"] == 2


def test_persistent_failure_returns_false_and_cleans_up():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "1.mp4")
        _serve(download.Timeout("slow"))
        assert download.download_file("http://x/v", target, max_retries=2) is False
        assert os.listdir(d) == []  # no target, no .part left behind


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
