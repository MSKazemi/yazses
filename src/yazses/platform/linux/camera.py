"""Linux camera enumeration from V4L2 sysfs and ``/dev/v4l/by-id`` (no ``cv2``, no ioctl).

Reads names from ``/sys/class/video4linux/videoN/name``, skips metadata nodes (sysfs
``index`` other than 0, which UVC devices expose beside the real capture node) and
attaches the stable ``/dev/v4l/by-id`` entry name when udev made one. Roots are
constructor arguments so tests point them at a temporary tree. The BSDs share this backend;
without V4L2 sysfs it simply reports no cameras.
"""
from __future__ import annotations

import re
from pathlib import Path

from yazses.camera.devices import CameraDevice

_VIDEO = re.compile(r"^video(\d+)$")


class LinuxCameraEnumerator:
    def __init__(
        self,
        sysfs_root: Path | str = "/sys/class/video4linux",
        dev_root: Path | str = "/dev",
        by_id_root: Path | str = "/dev/v4l/by-id",
    ) -> None:
        self._sysfs = Path(sysfs_root)
        self._dev = Path(dev_root)
        self._by_id = Path(by_id_root)

    def _by_id_map(self) -> dict[str, str]:
        """``videoN`` -> by-id entry name, preferring the ``-video-index0`` link."""
        found: dict[str, str] = {}
        try:
            entries = sorted(self._by_id.iterdir())
        except OSError:
            return found
        for entry in entries:
            try:
                target = entry.resolve().name
            except OSError:
                continue
            if not _VIDEO.match(target):
                continue
            if target not in found or entry.name.endswith("-video-index0"):
                found[target] = entry.name
        return found

    def list_cameras(self) -> list[CameraDevice]:
        try:
            nodes = list(self._sysfs.iterdir())
        except OSError:
            return []
        by_id = self._by_id_map()
        cameras: list[CameraDevice] = []
        for node in nodes:
            match = _VIDEO.match(node.name)
            if not match:
                continue
            try:
                cap_index = (node / "index").read_text(encoding="utf-8").strip()
            except OSError:
                cap_index = "0"
            if cap_index not in ("", "0"):
                continue  # metadata / secondary node of the same physical camera
            try:
                name = (node / "name").read_text(encoding="utf-8").strip()
            except OSError:
                name = node.name
            cameras.append(
                CameraDevice(
                    name=name or node.name,
                    path=str(self._dev / node.name),
                    index=int(match.group(1)),
                    by_id=by_id.get(node.name, ""),
                )
            )
        return sorted(cameras, key=lambda d: d.index)
