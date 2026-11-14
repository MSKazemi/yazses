"""Make a husk ``cv2/`` the only OpenCV a test can see, whatever is installed.

Several tests build a *husk*: a ``cv2/`` namespace directory of contrib-only subfolders,
with no ``__init__.py`` and no native module -- what a half-deleted OpenCV leaves behind.
They put it first on ``sys.path`` and expect ``import cv2`` to find it. That only holds
when no real OpenCV exists: the import system records a namespace directory as a
*portion* and keeps searching later ``sys.path`` entries, and a regular ``cv2`` package
found further along (``uv run --extra gaze``, any dev machine with the camera features)
wins over it. The tests then read a whole OpenCV and fail for a reason that has nothing to
do with the code under test.

``install_husk_only(site)`` puts a finder at the front of ``sys.meta_path`` that resolves
``cv2`` (and its submodules) against ``site`` alone, so the husk is what imports. Nothing
else in the environment changes: every other module still resolves normally.

The module is stdlib-only on purpose: ``subprocess_prelude`` loads it by file path into a
fresh interpreter, so the subprocess does not need ``tests`` importable.
"""
from __future__ import annotations

import sys
from importlib.abc import MetaPathFinder
from importlib.machinery import PathFinder


class HuskOnlyCv2(MetaPathFinder):
    """Resolve ``cv2`` and ``cv2.*`` against one directory, ignoring the rest of sys.path."""

    def __init__(self, site: str) -> None:
        self.site = str(site)

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "cv2":
            return PathFinder.find_spec("cv2", [self.site])
        if fullname.startswith("cv2."):
            return PathFinder.find_spec(fullname, path)
        return None


def install_husk_only(site) -> HuskOnlyCv2:
    """Install the finder first on ``sys.meta_path``; returns it so a test can remove it."""
    finder = HuskOnlyCv2(str(site))
    sys.meta_path.insert(0, finder)
    return finder


def subprocess_prelude(site) -> str:
    """Source for ``python -c``: isolate cv2 to *site*, then run whatever follows.

    Loads this file by path, so the subprocess needs neither ``tests`` on its
    ``sys.path`` nor the repository as its working directory.
    """
    return (
        "import importlib.util as _u\n"
        f"_s = _u.spec_from_file_location('cv2_isolation', {__file__!r})\n"
        "_m = _u.module_from_spec(_s); _s.loader.exec_module(_m)\n"
        f"_m.install_husk_only({str(site)!r})\n"
    )
