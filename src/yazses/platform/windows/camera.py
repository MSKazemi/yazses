"""Windows camera enumeration via PowerShell ``Get-PnpDevice -Class Camera``.

UNVERIFIED on real hardware. DirectShow (what OpenCV uses) numbers cameras in its own
order, which PnP does not promise to match, so ``index`` is a best guess; the friendly
name is the stable handle. No ``cv2`` import, no camera is opened.
"""
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

from yazses.camera.devices import CameraDevice

_SCRIPT = (
    "Get-PnpDevice -Class Camera -PresentOnly | "
    "Select-Object FriendlyName,InstanceId | ConvertTo-Json -Compress"
)


def parse_pnp_json(text: str) -> list[CameraDevice]:
    """Parse the ``ConvertTo-Json`` output (one object or a list); ``[]`` if unreadable."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    items = [data] if isinstance(data, dict) else data
    cameras: list[CameraDevice] = []
    for item in items if isinstance(items, list) else []:
        name = item.get("FriendlyName") if isinstance(item, dict) else None
        if not name:
            continue
        cameras.append(
            CameraDevice(
                name=str(name), path=str(item.get("InstanceId", "") or ""),
                index=len(cameras), by_id="",
            )
        )
    return cameras


def _run() -> str:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SCRIPT],
        capture_output=True, text=True, timeout=20, check=False,
    ).stdout


class WindowsCameraEnumerator:
    def __init__(self, run: Callable[[], str] = _run) -> None:
        self._run = run

    def list_cameras(self) -> list[CameraDevice]:
        return parse_pnp_json(self._run())
