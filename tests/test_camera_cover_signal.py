"""The Linux hardware cover signal (#923), over a fake ``ioctl``: no device is opened."""
from __future__ import annotations

import errno
import struct
from pathlib import Path

from yazses.platform.linux import camera_cover as cc


class _Kernel:
    """Answers the three reads; ``privacy`` / ``switches`` hold the machine's state."""

    def __init__(self, privacy=None, switches=None, privacy_errno=errno.EINVAL):
        self.privacy = dict(privacy or {})  # "/dev/video0" -> value
        self.switches = dict(switches or {})  # event path -> (has_switch, closed)
        self.privacy_errno = privacy_errno
        self.opened: list[str] = []
        self.open_fds: dict[int, str] = {}

    def open(self, path, flags):
        self.opened.append(path)
        fd = len(self.opened)
        self.open_fds[fd] = path
        return fd

    def close(self, fd):
        del self.open_fds[fd]

    def ioctl(self, fd, request, buffer):
        path = self.open_fds[fd]
        if request == cc.VIDIOC_G_CTRL:
            if path not in self.privacy:
                raise OSError(self.privacy_errno, "no control")
            control, _ = struct.unpack("=Ii", buffer)
            assert control == cc.V4L2_CID_PRIVACY
            buffer[:] = struct.pack("=Ii", control, self.privacy[path])
            return
        has, closed = self.switches.get(path, (False, False))
        bit = has if request == cc.EVIOCGBIT_SW else has and closed
        if bit:
            buffer[cc.SW_CAMERA_LENS_COVER // 8] |= 1 << (cc.SW_CAMERA_LENS_COVER % 8)


def _signal(kernel, tmp_path, *, events=(), cameras=1):
    for name in events:
        (tmp_path / name).touch()
    return cc.LinuxCameraCoverSignal(
        ioctl=kernel.ioctl, opener=kernel.open, closer=kernel.close,
        input_root=tmp_path, camera_count=lambda: cameras,
    )


def test_ioctl_numbers_match_the_kernel_headers():
    assert cc.VIDIOC_G_CTRL == 0xC008561B
    assert cc.EVIOCGBIT_SW == 0x80084525
    assert cc.EVIOCGSW == 0x8008451B


def test_no_hardware_signal_is_none(tmp_path):
    kernel = _Kernel()
    signal = _signal(kernel, tmp_path)
    assert signal.covered(0) is None
    assert kernel.open_fds == {}


def test_privacy_control_reports_both_states(tmp_path):
    kernel = _Kernel(privacy={"/dev/video0": 1, "/dev/video2": 0})
    signal = _signal(kernel, tmp_path)
    assert signal.covered(0) is True
    assert signal.covered(2) is False
    assert kernel.open_fds == {}


def test_a_camera_without_the_control_is_not_reopened(tmp_path):
    kernel = _Kernel()
    signal = _signal(kernel, tmp_path)
    for _ in range(3):
        signal.covered(0)
    assert kernel.opened.count("/dev/video0") == 1


def test_a_busy_or_missing_node_is_asked_again(tmp_path):
    kernel = _Kernel(privacy_errno=errno.ENOENT)
    signal = _signal(kernel, tmp_path)
    assert signal.covered(0) is None
    kernel.privacy["/dev/video0"] = 1
    assert signal.covered(0) is True


def test_the_lens_switch_is_read_with_one_camera(tmp_path):
    event = str(tmp_path / "event3")
    kernel = _Kernel(switches={event: (True, True)})
    signal = _signal(kernel, tmp_path, events=("event0", "event3"))
    assert signal.covered(0) is True
    kernel.switches[event] = (True, False)
    assert signal.covered(0) is False
    # The search runs once; afterwards only the device carrying the switch is opened.
    assert kernel.opened.count(str(tmp_path / "event0")) == 1


def test_the_lens_switch_is_ignored_with_two_cameras(tmp_path):
    event = str(Path(tmp_path) / "event0")
    kernel = _Kernel(switches={event: (True, True)})
    signal = _signal(kernel, tmp_path, events=("event0",), cameras=2)
    assert signal.covered(0) is None


def test_unreadable_input_devices_are_no_signal(tmp_path):
    kernel = _Kernel()

    def refuse(path, flags):
        raise PermissionError(errno.EACCES, "not in the input group")

    (tmp_path / "event0").touch()
    signal = cc.LinuxCameraCoverSignal(
        ioctl=kernel.ioctl, opener=refuse, closer=kernel.close,
        input_root=tmp_path, camera_count=lambda: 1,
    )
    assert signal.covered(0) is None


def test_the_linux_bundle_offers_the_signal_as_a_factory():
    from yazses.platform.linux import _make_camera_cover

    assert isinstance(_make_camera_cover(), cc.LinuxCameraCoverSignal)
