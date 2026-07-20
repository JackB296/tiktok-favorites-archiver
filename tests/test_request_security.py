"""Request-origin policy for the localhost-only write surface."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import request_security


def _policy():
    return request_security.LocalRequestPolicy(
        {"localhost", "127.0.0.1", "::1"},
    )


def test_safe_requests_do_not_require_a_write_marker():
    assert _policy().allows("GET", "http", "localhost:8080", None, None) is True
    assert _policy().allows("GET", "http", "evil.example:8080", None, None) is False


def test_mutations_accept_the_custom_marker_or_an_exact_same_origin():
    policy = _policy()
    assert policy.allows(
        "POST", "http", "localhost:8080", None, request_security.REQUEST_MARKER,
    ) is True
    assert policy.allows(
        "DELETE", "http", "localhost:8080", "http://localhost:8080", None,
    ) is True
    assert policy.allows(
        "PATCH", "http", "[::1]:8080", "http://[::1]:8080", None,
    ) is True


def test_cross_site_forms_untrusted_hosts_and_unmarked_clients_are_rejected():
    policy = _policy()
    cases = (
        ("POST", "http", "localhost:8080", "https://evil.example", None),
        ("POST", "http", "evil.example:8080", "http://evil.example:8080", None),
        ("POST", "http", "localhost:8080", None, None),
        ("POST", "http", "localhost:8080", "null", None),
        ("POST", "http", "localhost:8080", "http://localhost:9000", None),
    )
    for request in cases:
        assert policy.allows(*request) is False, request


if __name__ == "__main__":
    import traceback

    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception:
            failures += 1
            print(f"FAIL {test.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failures else 0)
