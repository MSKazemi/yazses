"""Pure camera-choice logic: the device record, name matching, and the effective index.

Nothing here touches the OS, opens a camera or imports ``cv2``. Enumeration is injected as a
:class:`~yazses.platform.base.CameraEnumerator` (one implementation per OS under
``platform/<os>/camera.py``), so every rule below is tested with plain fakes.

The same rules as ``yazses audio use``: a name is a case-insensitive substring, an exact
name or stable id always wins, and a query several cameras answer to is *refused* rather than
resolved to whichever the OS lists first -- that order changes across a replug, which is
what pinning a camera exists to defeat.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CameraDevice:
    """One capture-capable camera as the OS lists it right now.

    ``index`` is what ``cv2.VideoCapture`` takes and is **not stable** (it renumbers after a
    replug). ``by_id`` is the OS's own stable handle when it has one (Linux
    ``/dev/v4l/by-id`` entry name); where it has none, :attr:`stable_id` falls back to
    the name.
    """

    name: str
    path: str
    index: int
    by_id: str = ""

    @property
    def stable_id(self) -> str:
        return self.by_id or self.name


class CameraBackend(Protocol):
    """Structural twin of ``platform.base.CameraEnumerator`` (kept here so this module
    imports nothing from the platform layer)."""

    def list_cameras(self) -> list[CameraDevice]: ...


def list_cameras(backend: CameraBackend) -> list[CameraDevice]:
    """The cameras *backend* reports, ordered by index. Propagates a backend failure."""
    return sorted(backend.list_cameras(), key=lambda d: (d.index, d.name))


@dataclass(frozen=True)
class CameraResolution:
    """Outcome of resolving a query: one device, an ambiguity, or nothing."""

    device: CameraDevice | None
    candidates: tuple[CameraDevice, ...]

    @property
    def ambiguous(self) -> bool:
        return self.device is None and len(self.candidates) > 1


def resolve_camera(query: str, devices: Iterable[CameraDevice]) -> CameraResolution:
    """Resolve *query* against *devices*.

    An exact (case-insensitive) match of the stable id, the name or the path wins when it
    is unique. Otherwise the query is a substring of the name, stable id or path; one hit
    resolves, several are returned as ``candidates`` with ``device=None`` so the caller can
    refuse, and none gives an empty resolution.
    """
    needle = (query or "").strip().lower()
    pool = list(devices)
    if not needle:
        return CameraResolution(None, ())
    exact = [
        d for d in pool
        if needle in (d.stable_id.lower(), d.name.lower(), d.path.lower())
    ]
    if len(exact) == 1:
        return CameraResolution(exact[0], tuple(exact))
    hits = exact or [
        d for d in pool
        if needle in d.name.lower() or needle in d.stable_id.lower() or needle in d.path.lower()
    ]
    if len(hits) == 1:
        return CameraResolution(hits[0], tuple(hits))
    return CameraResolution(None, tuple(hits))


def effective_camera_index(shared_index: int, legacy_index: int) -> int:
    """The index a camera feature should open.

    ``[camera] index`` (``-1`` = not chosen) wins when set; otherwise the feature's own
    legacy ``camera_index`` applies, so an install that never ran ``yazses camera use``
    behaves exactly as before.
    """
    try:
        shared = int(shared_index)
    except (TypeError, ValueError):
        return legacy_index
    return shared if shared >= 0 else legacy_index
