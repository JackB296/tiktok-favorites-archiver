"""Tests for the supported ``python -m core`` command entry point."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.__main__ import main


def test_main_requires_a_supported_command():
    try:
        main([])
    except SystemExit as error:
        assert "python -m core {sync|backfill|enrich}" in str(error)
    else:
        raise AssertionError("expected a missing command to exit")


if __name__ == "__main__":
    test_main_requires_a_supported_command()
    print("PASS test_main_requires_a_supported_command")
