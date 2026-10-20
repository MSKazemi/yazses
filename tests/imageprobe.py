"""Load `scripts/imagediff.py` for the tests that compare committed artwork.

One loader rather than one per test file, so every artwork guard in the suite compares
with the same measured tolerance. Imported by name from `tests/`, which keeps it out of
`tests/test_freebsd_job_can_import_the_suite.py`'s dependency sweep — and nothing here
imports Pillow at module scope, so a file importing this still *collects* on the FreeBSD
leg, where Pillow is best-effort and may be absent.
"""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from types import ModuleType

import pytest

_SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "imagediff.py"


@lru_cache(maxsize=1)
def image_diff() -> ModuleType:
    """`scripts/imagediff.py`, or skip the calling test when Pillow is absent."""
    pytest.importorskip("PIL", reason="comparing images needs Pillow")
    spec = importlib.util.spec_from_file_location("imagediff", _SOURCE)
    assert spec and spec.loader, f"cannot load {_SOURCE}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
