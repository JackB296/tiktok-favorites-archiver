"""Ensure the repo root is importable as the package root during tests."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
