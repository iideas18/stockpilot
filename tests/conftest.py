"""Pytest fixtures and path setup."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the tests/ dir is importable so sibling helper modules like
# ``reliability_fakes`` resolve without needing a package marker.
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
