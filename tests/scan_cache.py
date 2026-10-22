"""Run a repository scan once per test session, not once per test.

Many guards in this suite read the whole source tree: they parse every module under
`src/yazses/` and report what they find. That is the right way to write a guard: the
region is derived from the tree, not written out by hand. But a guard module usually
has several tests that each want the same answer, and each one used to re-parse the
tree to get it. `test_egress_inventory.py` alone parsed all ~680 modules a dozen
times per run.

Nothing changes the tree while the suite runs, so the answer cannot change between
those calls. `scan_once` computes it on first use and gives every caller its own deep
copy, so a test that edits what it was handed cannot change what the next one sees.

**Only decorate a scan that takes no hidden input.** Its result may depend on its
arguments, which are part of the cache key, and on the repository. It must not depend
on anything a test can patch: a module global swapped with `monkeypatch`, an
environment variable, or a `tmp_path` the test builds. A cached scan would answer such
a test with the real tree's result, and that test is usually the one proving the
detector can fire. Keep those scans uncached, or give them the variable input as an
argument.
"""

from __future__ import annotations

import copy
import functools
from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def scan_once(fn: Callable[P, R]) -> Callable[P, R]:
    """Cache *fn* for the session and return a private deep copy on every call."""
    cached = functools.cache(fn)

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return copy.deepcopy(cached(*args, **kwargs))

    wrapper.cache_clear = cached.cache_clear  # type: ignore[attr-defined]
    return wrapper
