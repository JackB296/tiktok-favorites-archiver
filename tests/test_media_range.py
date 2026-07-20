"""HTTP byte-range parsing for securely opened Archive media."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import media_range


def test_byte_ranges_cover_bounded_open_ended_and_suffix_forms():
    assert media_range.parse_byte_range(None, 10) is None
    assert media_range.parse_byte_range("bytes=2-5", 10) == (2, 5)
    assert media_range.parse_byte_range("bytes=7-", 10) == (7, 9)
    assert media_range.parse_byte_range("bytes=-3", 10) == (7, 9)
    assert media_range.parse_byte_range("bytes=8-99", 10) == (8, 9)


def test_invalid_or_multiple_ranges_are_rejected():
    for value, size in (
        ("items=0-1", 10),
        ("bytes=1-0", 10),
        ("bytes=10-", 10),
        ("bytes=-0", 10),
        ("bytes=0-1,4-5", 10),
        ("bytes=0-0", 0),
    ):
        try:
            media_range.parse_byte_range(value, size)
        except media_range.RangeNotSatisfiable:
            pass
        else:
            raise AssertionError(f"accepted invalid range: {value!r}")


if __name__ == "__main__":
    test_byte_ranges_cover_bounded_open_ended_and_suffix_forms()
    test_invalid_or_multiple_ranges_are_rejected()
    print("PASS test_byte_ranges_cover_bounded_open_ended_and_suffix_forms")
    print("PASS test_invalid_or_multiple_ranges_are_rejected")
