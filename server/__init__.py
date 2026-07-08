"""FastAPI backend for the TikTok favorites archive app.

``serializers`` and ``jobs`` are standard-library-only (no FastAPI import), so
their logic is unit-testable without installing FastAPI; ``api``/``main`` are the
thin FastAPI wiring layer.
"""
