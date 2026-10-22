"""Is OpenCV (``cv2``) half-deleted? Answered from the file system, without importing it.

``opencv-python`` and ``opencv-contrib-python`` are separate distributions that write
the same ``cv2/`` package. Up to 2.43.2 the camera features installed both. Removing
either one -- an older YazSes's ``uv tool upgrade``, a manual ``uv sync``, ``pip
uninstall opencv-python`` -- deletes every file in its RECORD, including the ones the
other build also wrote. What is left is a directory of contrib-only subfolders with no
``__init__.py`` and no native module: ``import cv2`` still succeeds (as a namespace
package), ``importlib.util.find_spec("cv2")`` still finds it, and the camera features
crash later with ``AttributeError: module 'cv2' has no attribute 'VideoCapture'``.

``system/updater.py`` keeps an upgrade made by *this* updater from doing that and checks
the result in a subprocess. This module is the backstop for every other route: the one
cheap question the daemon's start-up check (``system/dormant.py``) and ``yazses doctor``
ask. It never imports ``cv2`` -- that loads OpenCV's native library, which a start must
not pay for -- and its common answer costs one ``find_spec`` and one directory listing:

* ``cv2`` not found at all: not half-deleted (that is "not installed", which the
  ordinary missing-library check already reports).
* ``cv2`` has its native module (``cv2/cv2.abi3.so``, ``cv2/cv2.pyd`` …, or ``cv2`` is
  itself an extension module): whole. ``importlib.metadata`` is never touched.
* otherwise -- a namespace package, or a package with no native module -- it is
  half-deleted when an OpenCV distribution still claims to be installed. Only on this
  path is the metadata read.

The specific, checkable signal (AGENTS.md rule 9) is the missing native module of a
package that pip/uv metadata says is installed. Every OpenCV wheel ships that module at
the top of ``cv2/`` (the reproduction in ``updater.py``'s notes left exactly the contrib
subfolders behind and nothing else).
"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterable

#: The distribution mediapipe requires and the camera features need.
CV2_CONTRIB = "opencv-contrib-python"

#: Every PyPI distribution that writes the top-level ``cv2/`` package.
CV2_DISTRIBUTIONS = (
    CV2_CONTRIB,
    "opencv-python",
    "opencv-python-headless",
    "opencv-contrib-python-headless",
)

#: The import name the camera features list in their ``check_modules``. A feature uses
#: OpenCV exactly when the registry says it checks for this module.
CV2_MODULE = "cv2"


def installed_cv2_versions() -> dict[str, str]:
    """``{distribution: version}`` for the ``cv2`` owners installed in the running
    environment, read from its metadata in this process. Never raises; ``{}`` on error.

    The caches are invalidated first: an upgrade or uninstall may have changed the
    environment since this process last looked.
    """
    try:
        import importlib
        import importlib.metadata as metadata

        importlib.invalidate_caches()
        found: dict[str, str] = {}
        for name in CV2_DISTRIBUTIONS:
            try:
                found[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                pass
        return found
    except Exception:  # noqa: BLE001 - a health probe must never raise
        return {}


def _find_cv2_spec():
    import importlib.util

    try:
        return importlib.util.find_spec(CV2_MODULE)
    except (ImportError, ValueError):
        return None


def _extension_suffixes() -> tuple[str, ...]:
    from importlib.machinery import EXTENSION_SUFFIXES

    return tuple(EXTENSION_SUFFIXES)


def _is_native_module(name: str, suffixes: Iterable[str]) -> bool:
    return name.startswith(CV2_MODULE + ".") and name.endswith(tuple(suffixes))


def cv2_package_whole(
    spec,
    *,
    listdir: Callable[[str], Iterable[str]] = os.listdir,
    suffixes: Iterable[str] | None = None,
) -> bool:
    """Does the ``cv2`` that *spec* describes carry its native module? Pure given *listdir*.

    ``True`` for a ``cv2`` that is itself an extension module (a distribution package
    such as Debian's ``python3-opencv``), and for a ``cv2/`` package with a
    ``cv2.<suffix>`` beside its ``__init__.py``. ``False`` for a namespace package
    (no ``__init__.py``: ``spec.origin`` is ``None``) and for a package whose native
    module is gone. *spec* must not be ``None``.
    """
    sfx = tuple(suffixes) if suffixes is not None else _extension_suffixes()
    origin = getattr(spec, "origin", None)
    locations = getattr(spec, "submodule_search_locations", None)
    if origin in (None, "namespace"):
        return False
    if locations is None:
        return True  # a plain module, not a package: the import machinery found a file
    for where in locations:
        try:
            names = list(listdir(where))
        except OSError:
            continue
        if any(_is_native_module(n, sfx) for n in names):
            return True
    return False


def cv2_half_deleted(
    *,
    find_spec: Callable[[], object] | None = None,
    versions: Callable[[], dict[str, str]] | None = None,
    listdir: Callable[[str], Iterable[str]] = os.listdir,
    frozen: bool | None = None,
) -> bool:
    """The one decision: an OpenCV distribution is installed, and ``cv2`` is importable
    only as a husk -- a namespace package, or a package without its native module, so
    ``cv2.VideoCapture`` and ``cv2.cvtColor`` do not exist.

    ``False`` when ``cv2`` is not found at all (not installed is a different finding)
    and when it is whole. Never imports ``cv2``; reads package metadata only when the
    directory already looks broken. Never raises. Every probe is injectable for tests.
    """
    # A frozen app (PyInstaller) is never half-deleted by pip, and an ADR-028 pack that
    # brought cv2 in has its own RECORD.json validation; its file layout may not match
    # `cv2/cv2.<suffix>`, which would tell every camera user to run a repair that cannot
    # run there. So the answer in a bundle is "whole".
    if getattr(sys, "frozen", False) if frozen is None else frozen:
        return False
    try:
        spec = (find_spec or _find_cv2_spec)()
        if spec is None:
            return False
        if cv2_package_whole(spec, listdir=listdir):
            return False
        return bool((versions or installed_cv2_versions)())
    except Exception:  # noqa: BLE001 - a health probe must never raise
        return False


def uses_cv2(feat) -> bool:
    """Whether a feature registry row (``features.feature_status``) imports ``cv2``.

    Derived from the row's own ``check_modules`` -- gaze, facegesture, headpointer,
    gesture and handsfree today -- so a camera feature added tomorrow is covered.
    """
    return CV2_MODULE in tuple(getattr(feat, "check_modules", ()) or ())
