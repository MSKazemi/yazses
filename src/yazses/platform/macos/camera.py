"""macOS camera enumeration via ``system_profiler SPCameraDataType -json``.

UNVERIFIED on real hardware. The list order is assumed (not proven) to match the order
OpenCV's AVFoundation backend numbers cameras in, so ``index`` is a best guess; the name
is the stable handle. No ``cv2`` import, no camera is opened.
"""
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

from yazses.camera.devices import CameraDevice


def parse_system_profiler(text: str) -> list[CameraDevice]:
    """Parse ``system_profiler SPCameraDataType -json`` output; ``[]`` on anything unreadable."""
    try:
        items = json.loads(text).get("SPCameraDataType", [])
    except (ValueError, AttributeError):
        return []
    cameras: list[CameraDevice] = []
    for item in items if isinstance(items, list) else []:
        name = item.get("_name") if isinstance(item, dict) else None
        if not name:
            continue
        uid = str(item.get("spcamera_unique-id", "") or "")
        cameras.append(CameraDevice(name=str(name), path=uid, index=len(cameras), by_id=""))
    return cameras


def _run() -> str:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["/usr/sbin/system_profiler", "SPCameraDataType", "-json"],
        capture_output=True, text=True, timeout=15, check=False,
    ).stdout


class MacosCameraEnumerator:
    def __init__(self, run: Callable[[], str] = _run) -> None:
        self._run = run

    def list_cameras(self) -> list[CameraDevice]:
        return parse_system_profiler(self._run())
