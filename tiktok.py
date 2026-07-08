"""Backwards-compatible entry point.

The implementation now lives in the ``core`` package; ``python tiktok.py`` and
``python -m core`` both run the same CLI download flow.
"""
from core.cli import main

if __name__ == "__main__":
    main()
