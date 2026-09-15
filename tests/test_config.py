"""Tests for core.config — environment parsing names the offending variable."""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _reload_with(**env):
    """Reload core.config with the given variables set (None = unset).

    The environment is restored afterwards so other test files, which rely on
    the defaults, never see a leftover override.
    """
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update({k: v for k, v in env.items() if v is not None})
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
    try:
        import core.config
        return importlib.reload(core.config)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_defaults_and_valid_overrides_parse():
    module = _reload_with(CONCURRENCY="6", RATE_PERIOD=" 0.5 ")
    assert module.CONCURRENCY == 6 and module.RATE_PERIOD == 0.5


def test_empty_value_falls_back_to_default():
    module = _reload_with(CONCURRENCY="")
    assert module.CONCURRENCY == 4


def test_malformed_value_names_the_variable():
    try:
        _reload_with(RATE_MAX_CALLS="four")
    except ValueError as error:
        assert "RATE_MAX_CALLS='four'" in str(error) and "default (8)" in str(error)
    else:
        raise AssertionError("malformed RATE_MAX_CALLS was accepted")


def test_below_minimum_is_rejected():
    try:
        _reload_with(CONCURRENCY="0")
    except ValueError as error:
        assert "CONCURRENCY='0' must be at least 1" in str(error)
    else:
        raise AssertionError("CONCURRENCY=0 was accepted")
    _reload_with()  # leave the module in its default state for other tests


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
