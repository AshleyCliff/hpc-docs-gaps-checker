"""Shared pytest fixtures for the charm-inventory extractor tests.

Adds `extractors/` to sys.path so tests can `import code_facts`, etc.,
directly rather than shelling out -- faster, and gives real tracebacks on
failure. The extractors remain runnable as scripts; this is purely a test
concern.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACTORS_DIR = REPO_ROOT / "extractors"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

if str(EXTRACTORS_DIR) not in sys.path:
    sys.path.insert(0, str(EXTRACTORS_DIR))
