"""Core package for the TikTok favorites downloader / archive app.

Split out of the original single-file ``tiktok.py``. Heavy third-party imports
(``requests``, ``moviepy``, ``PIL``) live only in ``cobalt``/``download``/
``slideshow`` so that ``config``, ``export``, and ``manifest`` stay importable
with the standard library alone (which keeps their logic unit-testable without
those packages installed).
"""
