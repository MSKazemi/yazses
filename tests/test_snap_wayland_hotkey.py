"""Which hold-to-talk listener a snap uses, and that `doctor` says which.

The snap took the X11 key grab whenever ``DISPLAY`` was set. On Wayland that is the
XWayland server, so the grab sees the key only while an X11 window is focused, even
for a user who had connected ``raw-input`` and joined the ``input`` group, whose
keyboards could be read directly and for every window.
"""
from __future__ import annotations

import pytest

evdev = pytest.importorskip("evdev")

from yazses.platform import linux as linux_platform  # noqa: E402
from yazses.platform.linux import hotkey as linux_hotkey  # noqa: E402
from yazses.platform.linux import hotkey_xgrab  # noqa: E402
from yazses.system import doctor  # noqa: E402

WAYLAND = {
    "SNAP": "/snap/yazses/1",
    "DISPLAY": ":0",
    "XDG_SESSION_TYPE": "wayland",
    "WAYLAND_DISPLAY": "wayland-0",
}
X11 = {"SNAP": "/snap/yazses/1", "DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}


def _choose(env, readable: bool) -> str:
    return linux_platform.snap_hotkey_listener(env, "right_ctrl", probe=lambda _k: readable)


def test_wayland_with_a_readable_keyboard_reads_it_directly():
    assert _choose(WAYLAND, True) == "evdev"


def test_wayland_without_keyboard_access_keeps_the_x11_grab():
    assert _choose(WAYLAND, False) == "x11"


def test_an_x11_session_keeps_the_grab_even_with_keyboard_access():
    """The grab works for every window there and consumes the key."""
    assert _choose(X11, True) == "x11"


def test_an_x11_session_never_opens_the_keyboards():
    def probe(_key):
        raise AssertionError("opened /dev/input on a session that does not need it")

    assert linux_platform.snap_hotkey_listener(X11, "right_ctrl", probe=probe) == "x11"


@pytest.mark.parametrize("missing", ["SNAP", "DISPLAY"])
def test_outside_a_snap_or_without_x_it_is_evdev_as_before(missing):
    env = {k: v for k, v in WAYLAND.items() if k != missing}
    assert _choose(env, False) == "evdev"


# -- the probe opens the device; permission bits cannot answer this -----------


class _Dev:
    def __init__(self, name: str, keys: set[int]) -> None:
        self.name = name
        self._keys = keys
        self.closed = False

    def capabilities(self):
        return {evdev.ecodes.EV_KEY: sorted(self._keys)}

    def close(self) -> None:
        self.closed = True


_FULL = {
    getattr(evdev.ecodes, f"KEY_{c}") for c in "QWERTYUIOPASDFGHJKLZXCVBNM"
} | {evdev.ecodes.KEY_ENTER, evdev.ecodes.KEY_RIGHTCTRL}


def _devices(monkeypatch, nodes: dict):
    monkeypatch.setattr(evdev, "list_devices", lambda: list(nodes))

    def open_node(path):
        dev = nodes[path]
        if isinstance(dev, Exception):
            raise dev
        return dev

    monkeypatch.setattr(evdev, "InputDevice", open_node)


def test_the_probe_accepts_a_real_keyboard_and_closes_it(monkeypatch):
    keyboard = _Dev("AT Translated Set 2 keyboard", _FULL)
    _devices(monkeypatch, {"/dev/input/event2": keyboard})
    assert linux_hotkey.can_read_keyboard("right_ctrl") is True
    assert keyboard.closed


def test_the_probe_refuses_when_confinement_blocks_the_open(monkeypatch):
    _devices(monkeypatch, {"/dev/input/event2": PermissionError(13, "denied")})
    assert linux_hotkey.can_read_keyboard("right_ctrl") is False


@pytest.mark.parametrize(
    "device",
    [
        _Dev("ydotoold virtual device", _FULL),
        _Dev("Power Button", {evdev.ecodes.KEY_RIGHTCTRL}),
        _Dev("keyboard without the key", _FULL - {evdev.ecodes.KEY_RIGHTCTRL}),
    ],
    ids=["virtual", "not-a-keyboard", "no-hotkey"],
)
def test_the_probe_wants_a_real_full_keyboard_with_the_hotkey(monkeypatch, device):
    _devices(monkeypatch, {"/dev/input/event5": device})
    assert linux_hotkey.can_read_keyboard("right_ctrl") is False


def test_the_probe_never_raises(monkeypatch):
    def broken():
        raise OSError("no /dev/input")

    monkeypatch.setattr(evdev, "list_devices", broken)
    assert linux_hotkey.can_read_keyboard("right_ctrl") is False


# -- the factory ---------------------------------------------------------------


class _Backend:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class _Grab(_Backend):
    pass


class _Evdev(_Backend):
    pass


def _build(monkeypatch, env, readable):
    for name in ("SNAP", "DISPLAY", "XDG_SESSION_TYPE", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(linux_hotkey, "can_read_keyboard", lambda _k: readable)
    monkeypatch.setattr(linux_hotkey, "LinuxHotkey", _Evdev)
    monkeypatch.setattr(hotkey_xgrab, "X11GrabHotkey", _Grab)
    return linux_platform._make_hotkey("right_ctrl", 500, lambda _n: None, lambda: None)


def test_the_factory_builds_the_direct_listener(monkeypatch):
    assert isinstance(_build(monkeypatch, WAYLAND, True), _Evdev)


def test_the_factory_warns_when_wayland_is_left_with_the_grab(monkeypatch, caplog):
    with caplog.at_level("WARNING"):
        backend = _build(monkeypatch, WAYLAND, False)
    assert isinstance(backend, _Grab)
    assert "X11 window" in caplog.text
    assert "raw-input" in caplog.text and "input` group" in caplog.text


def test_the_factory_is_quiet_on_x11(monkeypatch, caplog):
    with caplog.at_level("WARNING"):
        backend = _build(monkeypatch, X11, False)
    assert isinstance(backend, _Grab)
    assert not caplog.text


# -- doctor --------------------------------------------------------------------


def _check(env, readable):
    return doctor._snap_hotkey_listener_check(
        "linux", "right_ctrl", env=env, probe=lambda _k: readable
    )


def test_doctor_warns_that_the_grab_misses_wayland_windows():
    name, status, detail = _check(WAYLAND, False)
    assert (name, status) == ("Hotkey listener", "WARN")
    assert "X11 window" in detail
    assert "snap connect yazses:raw-input" in detail
    assert "usermod -aG input" in detail


def test_doctor_reports_direct_reading():
    assert _check(WAYLAND, True)[1] == "OK"


def test_doctor_reports_the_grab_as_fine_on_x11():
    name, status, detail = _check(X11, False)
    assert status == "OK"
    assert "X11" in detail


@pytest.mark.parametrize("platform_name,env", [("macos", WAYLAND), ("linux", {})])
def test_doctor_says_nothing_outside_a_linux_snap(platform_name, env):
    assert doctor._snap_hotkey_listener_check(platform_name, "right_ctrl", env=env) is None
