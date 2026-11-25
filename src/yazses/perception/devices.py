"""Camera enumeration and name/path resolution (#924 items 2-4).

``cv2.VideoCapture(0)`` is a guess: index 0 is whichever device the kernel listed
first, and a laptop with a virtual camera or a second webcam gets the wrong one. This
module lets the user say *which* camera, by the name the system gives it or by its
stable ``/dev/v4l/by-id/...`` path, and turns that into the integer index the capture
backends open.

Pure and dependency-free: no OpenCV, no threads. The one thing that touches the
machine is an *enumerator* (a callable returning :class:`CameraDevice` rows), which is
injected. Two ready-made ones are here: :func:`enumerate_v4l` (Linux: reads
``/sys/class/video4linux`` and ``/dev/v4l/by-id``, both roots injectable) and
:func:`enumerate_by_probe` (other systems: an injected ``probe(index) -> bool``, which
the caller backs with a lazily imported ``cv2``).

Nothing is persisted; the choice is a runtime state (ADR-030 freezes the config).
"""
from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "CameraDevice",
    "Resolution",
    "default_enumerator",
    "enumerate_by_probe",
    "enumerate_v4l",
    "format_devices",
    "resolve_camera",
]

log = logging.getLogger(__name__)

Enumerator = Callable[[], list["CameraDevice"]]

V4L_SYS = Path("/sys/class/video4linux")
V4L_BY_ID = Path("/dev/v4l/by-id")
#: How many indexes the probe-based enumerator tries; cameras beyond this are not listed.
PROBE_LIMIT = 8
_VIDEO_NODE = re.compile(r"^video(\d+)$")


@dataclass(frozen=True)
class CameraDevice:
    """One camera: the integer index OpenCV opens, a display name, and stable paths."""

    index: int
    name: str
    #: ``/dev/v4l/by-id/...`` and ``/dev/videoN`` spellings that mean this device.
    paths: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {"index": self.index, "name": self.name, "paths": list(self.paths)}


@dataclass(frozen=True)
class Resolution:
    """Outcome of :func:`resolve_camera`: a device, or why there is none."""

    device: CameraDevice | None
    #: ``""`` on success, else ``"empty"``, ``"missing"`` or ``"ambiguous"``.
    problem: str = ""
    #: The devices a user should choose among (all of them when missing, the matches
    #: when ambiguous).
    candidates: tuple[CameraDevice, ...] = ()
    query: str = ""

    @property
    def ok(self) -> bool:
        return self.device is not None

    def message(self) -> str:
        """One sentence naming the problem and listing what to choose from."""
        if self.device is not None:
            return ""
        if self.problem == "empty":
            head = "No camera name or path was given."
        elif self.problem == "ambiguous":
            head = f"More than one camera matches {self.query!r}; be more specific."
        else:
            head = f"No camera matches {self.query!r}."
        if not self.candidates:
            return f"{head} No cameras were found."
        return f"{head}\n{format_devices(list(self.candidates))}"


def format_devices(devices: list[CameraDevice]) -> str:
    """The plain-text listing used by ``yazses camera list`` and by error messages."""
    if not devices:
        return "No cameras found."
    lines = []
    for dev in devices:
        lines.append(f"  {dev.index}: {dev.name}")
        for path in dev.paths:
            lines.append(f"       {path}")
    return "\n".join(lines)


def _is_path(q: str) -> bool:
    """A device path rather than a name: POSIX ``/dev/...`` or a Windows drive or UNC path."""
    return q.startswith(("/", "\\")) or os.path.isabs(q) or (len(q) > 2 and q[1] == ":" and q[2] in "\\/")


def resolve_camera(devices: list[CameraDevice], query: str) -> Resolution:
    """Pick one device by path, index, exact name or unique name fragment.

    Order: a ``/dev/...`` path (by-id or videoN), an integer index that is listed, an
    exact name (case-insensitive), then a name fragment. A name or fragment shared by
    two devices is ``ambiguous`` (two identical webcams share a name; use the by-id
    path or the index). Never raises and never guesses.
    """
    q = str(query or "").strip()
    everyone = tuple(devices)
    if not q:
        return Resolution(None, "empty", everyone, q)
    if _is_path(q):
        norm = os.path.normcase(os.path.normpath(q))
        hits = [d for d in devices
                if norm in (os.path.normcase(os.path.normpath(p)) for p in d.paths)]
        return _one(hits, everyone, q)
    if q.isdigit():
        hits = [d for d in devices if d.index == int(q)]
        return _one(hits, everyone, q)
    low = q.casefold()
    exact = [d for d in devices if d.name.casefold() == low]
    if exact:
        return _one(exact, everyone, q)
    frag = [d for d in devices if low in d.name.casefold()]
    return _one(frag, everyone, q)


def _one(hits: list[CameraDevice], everyone: tuple[CameraDevice, ...], q: str) -> Resolution:
    if len(hits) == 1:
        return Resolution(hits[0], "", (), q)
    if not hits:
        return Resolution(None, "missing", everyone, q)
    return Resolution(None, "ambiguous", tuple(hits), q)


def enumerate_v4l(sys_root: Path = V4L_SYS, by_id_root: Path = V4L_BY_ID) -> list[CameraDevice]:
    """Linux cameras from ``/sys/class/video4linux`` plus the stable by-id paths.

    A webcam exposes several ``/dev/videoN`` nodes (capture plus metadata); only the
    capture node (sysfs ``index`` file ``0``) is listed. Unreadable entries are
    skipped, never raised.
    """
    found: dict[int, str] = {}
    try:
        entries = sorted(sys_root.iterdir())
    except OSError:
        return []
    for entry in entries:
        match = _VIDEO_NODE.match(entry.name)
        if match is None:
            continue
        try:
            name = (entry / "name").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        try:
            node_index = (entry / "index").read_text(encoding="utf-8").strip()
        except OSError:
            node_index = "0"
        if node_index not in ("", "0"):
            continue
        found[int(match.group(1))] = name or f"video{match.group(1)}"

    by_id: dict[int, list[str]] = {}
    try:
        links = sorted(by_id_root.iterdir())
    except OSError:
        links = []
    for link in links:
        try:
            target = os.path.basename(os.path.realpath(link))
        except OSError:
            continue
        match = _VIDEO_NODE.match(target)
        if match is not None:
            by_id.setdefault(int(match.group(1)), []).append(str(link))

    devices = []
    for idx in sorted(found):
        paths = tuple(by_id.get(idx, ())) + (f"/dev/video{idx}",)
        devices.append(CameraDevice(idx, found[idx], paths))
    return devices


def enumerate_by_probe(
    probe: Callable[[int], bool], limit: int = PROBE_LIMIT
) -> list[CameraDevice]:
    """Cameras on systems with no device listing: try each index with *probe*.

    The probe opens (and closes) the device, so it cannot see a camera another
    program, or YazSes itself, is holding. Names are ``Camera N``: the platform gives
    no name through this route.
    """
    devices = []
    for index in range(max(0, int(limit))):
        try:
            present = bool(probe(index))
        except Exception:
            log.debug("camera probe %d raised", index, exc_info=True)
            present = False
        if present:
            devices.append(CameraDevice(index, f"Camera {index}"))
    return devices


def default_enumerator(
    probe: Callable[[int], bool] | None = None, sys_root: Path = V4L_SYS
) -> Enumerator:
    """sysfs listing where ``/sys/class/video4linux`` exists, an index probe elsewhere.

    Decided by what is on the machine, not by ``sys.platform``, so no OS branch lives
    here. Evaluated per call: nothing is read until a camera command asks.
    """
    chosen = probe if probe is not None else _cv2_probe

    def _enumerate() -> list[CameraDevice]:
        if sys_root.is_dir():
            return enumerate_v4l(sys_root)
        return enumerate_by_probe(chosen)

    return _enumerate


def _cv2_probe(index: int) -> bool:
    """Open ``cv2.VideoCapture(index)`` and report whether it opened. Imported lazily."""
    try:
        import cv2  # noqa: PLC0415 - optional dependency
    except ImportError:
        return False
    cap = cv2.VideoCapture(index)
    try:
        return bool(cap.isOpened())
    finally:
        cap.release()


def effective_camera_index(shared_index: int, legacy_index: int) -> int:
    """The index a camera feature should open.

    ``[camera] index`` (``-1`` = not chosen) wins when set; otherwise the feature's own
    legacy ``camera_index`` applies, so an install that never saved a choice behaves
    exactly as before.
    """
    try:
        shared = int(shared_index)
    except (TypeError, ValueError):
        return legacy_index
    return shared if shared >= 0 else legacy_index
