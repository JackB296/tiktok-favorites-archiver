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


def test_parse_extra_hosts_accepts_names_ports_wildcard_and_rejects_junk():
    parse = request_security.parse_extra_hosts
    assert parse(None) == frozenset()
    assert parse("") == frozenset()
    assert parse("nas.local") == {"nas.local"}
    assert parse("NAS.local:8080, machine.tailnet.ts.net ,") == {
        "nas.local", "machine.tailnet.ts.net",
    }
    assert parse("[fd7a::2]:8080") == {"fd7a::2"}
    assert parse("*") == {request_security.WILDCARD}
    for junk in ("user@nas.local", "http://nas.local", "nas.local/path"):
        try:
            parse(junk)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {junk!r}")


def test_extra_hosts_extend_but_do_not_replace_the_loopback_allowlist():
    policy = request_security.LocalRequestPolicy(
        request_security.DEFAULT_ALLOWED_HOSTS | {"nas.local"},
    )
    assert policy.allows("GET", "http", "nas.local:8080", None, None) is True
    assert policy.allows("GET", "http", "localhost:8080", None, None) is True
    assert policy.allows("GET", "http", "evil.example:8080", None, None) is False
    assert policy.allows(
        "POST", "http", "nas.local:8080", None, request_security.REQUEST_MARKER,
    ) is True
    assert policy.allows("POST", "http", "nas.local:8080", None, None) is False


def test_wildcard_allows_any_valid_host_but_still_requires_write_intent():
    policy = request_security.LocalRequestPolicy({request_security.WILDCARD})
    assert policy.allows("GET", "http", "anything.example:8080", None, None) is True
    assert policy.allows("GET", "http", "user@bad", None, None) is False
    assert policy.allows("POST", "http", "anything.example:8080", None, None) is False
    assert policy.allows(
        "POST", "http", "anything.example:8080", None, request_security.REQUEST_MARKER,
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
