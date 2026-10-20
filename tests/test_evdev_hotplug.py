"""Keyboards plugged in or pulled out while the evdev listener runs.

The listener used to enumerate /dev/input once, at start: a USB keyboard docked
to a laptop afterwards was never opened, so its Right Ctrl did nothing until the
daemon restarted. Unplugging a keyboard that *was* open was worse — the read
raised ENODEV, ``run()`` re-raised it, and the daemon shut down.
"""

import errno
from types import SimpleNamespace

import pytest

pytest.importorskip("evdev", reason="evdev is a Linux-only dependency")

from evdev import ecodes

from yazses.hotkeys import evdev_hold
from yazses.hotkeys.evdev_hold import EvdevHoldListener

_LETTERS = {getattr(ecodes, f"KEY_{c}") for c in "QWERTYUIOPASDFGHJKLZXCVBNM"}
_FULL_KEYBOARD = _LETTERS | {ecodes.KEY_ENTER, ecodes.KEY_SPACE, ecodes.KEY_RIGHTCTRL}
_KEY = ecodes.KEY_RIGHTCTRL


class _FakeDevice:
    _next_fd = 100
    by_fd: dict = {}

    def __init__(self, path, name, keys=_FULL_KEYBOARD):
        self.path = path
        self.name = name
        self._keys = set(keys)
        _FakeDevice._next_fd += 1
        self.fd = _FakeDevice._next_fd
        _FakeDevice.by_fd[self.fd] = self
        self.pending = []
        self.gone = False
        self.closed = False

    def capabilities(self):
        return {ecodes.EV_KEY: sorted(self._keys)}

    def read(self):
        if self.gone:
            raise OSError(errno.ENODEV, "No such device")
        events, self.pending = self.pending, []
        return events

    def close(self):
        self.closed = True

    def press(self, value):
        self.pending.append(SimpleNamespace(type=ecodes.EV_KEY, code=_KEY, value=value))


class _Machine:
    """/dev/input as a dict the test edits between listener iterations."""

    def __init__(self, mocker, *devices):
        self.nodes = {d.path: d for d in devices}
        self.inodes = {d.path: i for i, d in enumerate(devices, start=1)}
        self._next_inode = len(devices) + 1  # never reused, like a real filesystem
        self.opened = []
        mocker.patch.object(evdev_hold.evdev, "list_devices", side_effect=lambda: list(self.nodes))
        mocker.patch.object(evdev_hold.evdev, "InputDevice", side_effect=self._open)
        mocker.patch.object(evdev_hold, "_node_identity", side_effect=self.inodes.get, create=True)

    def _open(self, path):
        if path not in self.nodes:
            raise OSError(errno.ENOENT, "No such file")
        self.opened.append(path)
        return self.nodes[path]

    def plug(self, dev):
        self.nodes[dev.path] = dev
        self.inodes[dev.path] = self._next_inode
        self._next_inode += 1

    def unplug(self, dev):
        dev.gone = True
        del self.nodes[dev.path]
        del self.inodes[dev.path]


def _listener():
    starts, ends = [], []
    lis = EvdevHoldListener(
        200,
        on_hold_start=starts.append,
        on_hold_end=lambda: ends.append(True),
        key_code=_KEY,
    )
    return lis, starts, ends


def _run(mocker, lis, steps):
    """Run the real loop; before each select, apply the next step, and report as
    readable every open device with something to say (events, or a removal)."""
    mocker.patch.object(evdev_hold, "_RESCAN_INTERVAL_S", 0.0, create=True)
    steps = list(steps)

    def fake_select(fds, _w, _x, _timeout):
        if not steps:
            lis._stopping = True
            return [], [], []
        steps.pop(0)()
        devs = _FakeDevice.by_fd
        ready = [fd for fd in fds if devs[fd].pending or devs[fd].gone]
        return ready, [], []

    mocker.patch.object(evdev_hold.select, "select", side_effect=fake_select)
    lis.run()


def test_keyboard_plugged_in_after_start_triggers_the_hotkey(mocker):
    laptop = _FakeDevice("/dev/input/event3", "AT Translated Set 2 keyboard")
    usb = _FakeDevice("/dev/input/event15", "MOSART Semi. 2.4G INPUT DEVICE")
    machine = _Machine(mocker, laptop)
    lis, starts, ends = _listener()

    _run(mocker, lis, [
        lambda: machine.plug(usb),
        lambda: None,              # the rescan after the previous select opens it
        lambda: usb.press(1),
        lambda: usb.press(0),
    ])

    assert starts == [0] and ends == [True]


def test_unplugging_a_keyboard_does_not_stop_the_listener(mocker):
    laptop = _FakeDevice("/dev/input/event3", "AT Translated Set 2 keyboard")
    usb = _FakeDevice("/dev/input/event15", "MOSART Semi. 2.4G INPUT DEVICE")
    machine = _Machine(mocker, laptop, usb)
    lis, starts, ends = _listener()

    _run(mocker, lis, [
        lambda: machine.unplug(usb),   # read() now raises ENODEV
        lambda: laptop.press(1),
        lambda: laptop.press(0),
    ])

    assert usb.closed
    assert starts == [0] and ends == [True]


def test_unplugging_mid_hold_ends_the_recording(mocker):
    """The release can never arrive from a device that is gone."""
    laptop = _FakeDevice("/dev/input/event3", "AT Translated Set 2 keyboard")
    usb = _FakeDevice("/dev/input/event15", "MOSART Semi. 2.4G INPUT DEVICE")
    machine = _Machine(mocker, laptop, usb)
    lis, starts, ends = _listener()

    _run(mocker, lis, [
        lambda: usb.press(1),
        lambda: machine.unplug(usb),
    ])

    assert starts == [0] and ends == [True]
    assert not lis._recording


def test_unplugging_another_keyboard_mid_hold_keeps_the_recording(mocker):
    laptop = _FakeDevice("/dev/input/event3", "AT Translated Set 2 keyboard")
    usb = _FakeDevice("/dev/input/event15", "MOSART Semi. 2.4G INPUT DEVICE")
    machine = _Machine(mocker, laptop, usb)
    lis, starts, ends = _listener()

    _run(mocker, lis, [
        lambda: laptop.press(1),
        lambda: machine.unplug(usb),
    ])

    assert starts == [0] and ends == []


def test_last_keyboard_unplugged_then_replugged(mocker):
    usb = _FakeDevice("/dev/input/event15", "MOSART Semi. 2.4G INPUT DEVICE")
    machine = _Machine(mocker, usb)
    lis, starts, ends = _listener()
    replug = _FakeDevice("/dev/input/event15", "MOSART Semi. 2.4G INPUT DEVICE")

    _run(mocker, lis, [
        lambda: machine.unplug(usb),
        lambda: None,                  # select on an empty fd list just waits
        lambda: machine.plug(replug),
        lambda: None,
        lambda: replug.press(1),
        lambda: replug.press(0),
    ])

    assert starts == [0] and ends == [True]


def test_refused_node_is_not_reopened_every_scan(mocker):
    laptop = _FakeDevice("/dev/input/event3", "AT Translated Set 2 keyboard")
    power = _FakeDevice("/dev/input/event1", "Power Button", {ecodes.KEY_POWER})
    machine = _Machine(mocker, laptop, power)
    lis, _, _ = _listener()
    lis._add(laptop)

    for _ in range(5):
        lis._rescan()

    assert machine.opened.count(power.path) == 1
    assert power.closed
    assert set(lis._keyboards.values()) == {laptop}


def test_reused_node_name_is_judged_again(mocker):
    """event15 refused, unplugged, and a keyboard plugged in under the same name
    before the next scan: the new inode says it is a different device."""
    laptop = _FakeDevice("/dev/input/event3", "AT Translated Set 2 keyboard")
    pad = _FakeDevice("/dev/input/event15", "Foot pedal", {ecodes.KEY_A})
    machine = _Machine(mocker, laptop, pad)
    lis, _, _ = _listener()
    lis._add(laptop)
    lis._rescan()
    assert pad not in lis._keyboards.values()

    usb = _FakeDevice("/dev/input/event15", "MOSART Semi. 2.4G INPUT DEVICE")
    machine.unplug(pad)
    machine.plug(usb)
    lis._rescan()

    assert usb in lis._keyboards.values()


def test_virtual_device_is_never_taken_on_hotplug(mocker):
    laptop = _FakeDevice("/dev/input/event3", "AT Translated Set 2 keyboard")
    ydotool = _FakeDevice("/dev/input/event20", "ydotoold virtual device")
    machine = _Machine(mocker, laptop)
    lis, _, _ = _listener()
    lis._add(laptop)

    machine.plug(ydotool)
    lis._rescan()

    assert set(lis._keyboards.values()) == {laptop}


def test_partial_device_reconsidered_once_the_full_keyboard_leaves(mocker):
    """While a full keyboard is held a partial block is refused, exactly as at
    startup; once the full one is gone the block is the best there is."""
    usb = _FakeDevice("/dev/input/event15", "MOSART Semi. 2.4G INPUT DEVICE")
    block = _FakeDevice("/dev/input/event8", "Macro pad", {_KEY})
    machine = _Machine(mocker, usb, block)
    lis, _, _ = _listener()
    lis._add(usb)
    lis._rescan()
    assert block not in lis._keyboards.values()

    machine.unplug(usb)
    lis._drop(usb.fd)
    lis._rescan()

    assert block in lis._keyboards.values()


def test_node_without_permissions_yet_is_retried(mocker):
    """udev applies the node's ACL a moment after creating it."""
    laptop = _FakeDevice("/dev/input/event3", "AT Translated Set 2 keyboard")
    usb = _FakeDevice("/dev/input/event15", "MOSART Semi. 2.4G INPUT DEVICE")
    machine = _Machine(mocker, laptop, usb)
    lis, _, _ = _listener()
    lis._add(laptop)
    real_open = machine._open
    mocker.patch.object(
        evdev_hold.evdev, "InputDevice",
        side_effect=OSError(errno.EACCES, "Permission denied"),
    )
    lis._rescan()
    assert usb not in lis._keyboards.values()

    mocker.patch.object(evdev_hold.evdev, "InputDevice", side_effect=real_open)
    lis._rescan()

    assert usb in lis._keyboards.values()
