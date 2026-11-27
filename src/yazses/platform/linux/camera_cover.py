"""The hardware's own word on a camera cover: V4L2 privacy control and lens-cover switch.

``platform.base.CameraCoverSignal`` for Linux (#923). Two sources, both optional and
absent on most machines:

* ``V4L2_CID_PRIVACY`` on ``/dev/videoN`` -- the camera's own control ("no image can be
  captured while it is set"). It names the camera, so it is trusted for that camera.
* ``SW_CAMERA_LENS_COVER`` on an input device -- a laptop's shutter switch. It does not
  say *which* camera it covers, so it is read only while the machine has exactly one:
  with a second, external camera plugged in, the lid's switch says nothing about it.

Both are plain ``ioctl`` reads: nothing is captured, no event is consumed and no input
is grabbed. Every failure (no permission on ``/dev/input``, no such control, a device
that went away) reads as ``None``, "no signal", and the frames are judged instead.

Stdlib only; ``fcntl`` is imported inside the one call that needs it.
"""
from __future__ import annotations

import errno
import logging
import os
import struct
from collections.abc import Callable
from pathlib import Path

__all__ = ["LinuxCameraCoverSignal"]

log = logging.getLogger(__name__)

#: ``V4L2_CID_CAMERA_CLASS_BASE + 16`` (linux/v4l2-controls.h).
V4L2_CID_PRIVACY = 0x009A0910
#: ``_IOWR('V', 27, struct v4l2_control)``: two 32-bit fields, id and value.
VIDIOC_G_CTRL = 0xC008561B
_V4L2_CONTROL = struct.Struct("=Ii")

#: ``linux/input-event-codes.h``.
EV_SW = 0x05
SW_CAMERA_LENS_COVER = 0x09
#: Room for the switch bitmap (``SW_MAX`` is well under 64).
_BITMAP_BYTES = 8


def _ioc_read(number: int, size: int) -> int:
    """``_IOC(_IOC_READ, 'E', number, size)`` for the evdev reads."""
    return (2 << 30) | (size << 16) | (ord("E") << 8) | number


EVIOCGBIT_SW = _ioc_read(0x20 + EV_SW, _BITMAP_BYTES)
EVIOCGSW = _ioc_read(0x1B, _BITMAP_BYTES)

#: ``(fd, request, buffer)``: fills *buffer* in place or raises ``OSError``.
Ioctl = Callable[[int, int, bytearray], None]


def _ioctl(fd: int, request: int, buffer: bytearray) -> None:
    import fcntl  # noqa: PLC0415 - POSIX only; tests inject their own

    fcntl.ioctl(fd, request, buffer, True)


def _open(path: str, flags: int) -> int:
    return os.open(path, flags | getattr(os, "O_NONBLOCK", 0))


def _camera_count() -> int:
    from yazses.perception.devices import enumerate_v4l

    return len(enumerate_v4l())


class LinuxCameraCoverSignal:
    """``covered(index)`` from the V4L2 privacy control, else the lens-cover switch."""

    def __init__(
        self,
        *,
        ioctl: Ioctl = _ioctl,
        opener: Callable[[str, int], int] = _open,
        closer: Callable[[int], None] = os.close,
        input_root: Path = Path("/dev/input"),
        camera_count: Callable[[], int] = _camera_count,
    ) -> None:
        self._ioctl = ioctl
        self._open = opener
        self._close = closer
        self._input_root = Path(input_root)
        self._camera_count = camera_count
        #: Camera nodes that answered "no such control": not opened again.
        self._no_control: set[int] = set()
        #: Input devices that carry the switch; found on first use, ``None`` before.
        self._switches: list[str] | None = None

    def covered(self, index: int) -> bool | None:
        control = self._privacy_control(int(index))
        if control:
            return True
        switch = self._lens_switch()
        if switch:
            return True
        if control is None and switch is None:
            return None
        return False

    # -- V4L2 --------------------------------------------------------------- #

    def _privacy_control(self, index: int) -> bool | None:
        if index < 0 or index in self._no_control:
            return None
        buffer = bytearray(_V4L2_CONTROL.pack(V4L2_CID_PRIVACY, 0))
        try:
            self._read(f"/dev/video{index}", os.O_RDWR, VIDIOC_G_CTRL, buffer)
        except OSError as exc:
            if exc.errno in (errno.EINVAL, errno.ENOTTY):
                self._no_control.add(index)
            return None
        except ImportError:
            return None
        return _V4L2_CONTROL.unpack(buffer)[1] != 0

    # -- input switch ------------------------------------------------------- #

    def _lens_switch(self) -> bool | None:
        try:
            if self._switches is None:
                self._switches = self._find_switches()
            if not self._switches or self._camera_count() != 1:
                return None
        except Exception:
            log.debug("camera cover: looking for a lens-cover switch failed", exc_info=True)
            return None
        answer: bool | None = None
        for path in self._switches:
            state = self._switch_bit(path, EVIOCGSW)
            if state:
                return True
            if state is False:
                answer = False
        return answer

    def _find_switches(self) -> list[str]:
        return [
            str(path)
            for path in sorted(self._input_root.glob("event*"))
            if self._switch_bit(str(path), EVIOCGBIT_SW)
        ]

    def _switch_bit(self, path: str, request: int) -> bool | None:
        buffer = bytearray(_BITMAP_BYTES)
        try:
            self._read(path, os.O_RDONLY, request, buffer)
        except (OSError, ImportError):
            return None
        return bool(buffer[SW_CAMERA_LENS_COVER // 8] & (1 << (SW_CAMERA_LENS_COVER % 8)))

    def _read(self, path: str, flags: int, request: int, buffer: bytearray) -> None:
        fd = self._open(path, flags)
        try:
            self._ioctl(fd, request, buffer)
        finally:
            self._close(fd)
