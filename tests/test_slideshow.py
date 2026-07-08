"""Tests for core.slideshow.compute_canvas_size (pure; no PIL/moviepy needed)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Prove the module imports without the heavy deps (they are lazy-imported).
for _m in ("PIL", "PIL.Image", "moviepy", "moviepy.editor"):
    sys.modules.setdefault(_m, None)

from core import slideshow


def test_canvas_is_largest_dimensions_even_rounded():
    # Widest is 1079, tallest is 1921 -> rounded up to even (1080, 1922).
    sizes = [(1079, 1920), (600, 1921), (1080, 800)]
    assert slideshow.compute_canvas_size(sizes) == (1080, 1922)


def test_canvas_no_downscale_uniform():
    sizes = [(1080, 1920), (1080, 1920)]
    assert slideshow.compute_canvas_size(sizes) == (1080, 1920)


def test_canvas_empty_and_odd():
    assert slideshow.compute_canvas_size([]) == (2, 2)
    assert slideshow.compute_canvas_size([(3, 5)]) == (4, 6)


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
