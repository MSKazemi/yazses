"""Regression tests for EvdevHoldListener keyboard-device selection.

The daemon must listen on the real hardware keyboard, never on the virtual
uinput device that injection tools (ydotool/wtype) create. That virtual device
advertises the full key range, so a naive "first device with this key" scan
picks it and never sees the user's keypresses (the hold-to-talk hotkey appears
dead). See evdev_hold._find_keyboard.
"""

import pytest

pytest.importorskip("evdev", reason="evdev is a Linux-only dependency")

from evdev import ecodes

from yazses.hotkeys.evdev_hold import EvdevHoldListener

_LETTERS = {getattr(ecodes, f"KEY_{c}") for c in "QWERTYUIOPASDFGHJKLZXCVBNM"}
_FULL_KEYBOARD = _LETTERS | {ecodes.KEY_ENTER, ecodes.KEY_SPACE, ecodes.KEY_RIGHTALT}


class _FakeDevice:
    def __init__(self, path, name, keys):
        self.path = path
        self.name = name
        self._keys = set(keys)

    def capabilities(self):
        return {ecodes.EV_KEY: sorted(self._keys)}


def _patch_devices(mocker, devices):
    by_path = {d.path: d for d in devices}
    mocker.patch(
        "yazses.hotkeys.evdev_hold.evdev.list_devices",
        return_value=list(by_path),
    )
    mocker.patch(
        "yazses.hotkeys.evdev_hold.evdev.InputDevice",
        side_effect=lambda p: by_path[p],
    )


def _listener(key_code=ecodes.KEY_SPACE):
    return EvdevHoldListener(200, lambda _l: None, lambda: None, key_code=key_code)


def test_skips_virtual_device_for_real_keyboard(mocker):
    """The ydotoold virtual device must lose to the real keyboard even when it
    is enumerated first."""
    virtual = _FakeDevice("/dev/input/event16", "ydotoold virtual device", _FULL_KEYBOARD)
    real = _FakeDevice("/dev/input/event3", "AT Translated Set 2 keyboard", _FULL_KEYBOARD)
    _patch_devices(mocker, [virtual, real])

    chosen = _listener()._find_keyboard()

    assert chosen.name == "AT Translated Set 2 keyboard"


def test_prefers_full_keyboard_over_partial_block(mocker):
    """A partial hotkey block that happens to expose the key loses to a full
    keyboard."""
    block = _FakeDevice("/dev/input/event8", "ThinkPad Extra Buttons", {ecodes.KEY_SPACE})
    real = _FakeDevice("/dev/input/event3", "AT Translated Set 2 keyboard", _FULL_KEYBOARD)
    _patch_devices(mocker, [real, block])

    chosen = _listener()._find_keyboard()

    assert chosen.name == "AT Translated Set 2 keyboard"


def test_falls_back_to_virtual_with_warning(mocker, caplog):
    """If only a virtual device exposes the key, use it but warn."""
    virtual = _FakeDevice("/dev/input/event16", "ydotoold virtual device", _FULL_KEYBOARD)
    _patch_devices(mocker, [virtual])

    with caplog.at_level("WARNING"):
        chosen = _listener()._find_keyboard()

    assert chosen.name == "ydotoold virtual device"
    assert any("virtual input device" in r.message for r in caplog.records)


def test_raises_when_no_device_has_key(mocker):
    other = _FakeDevice("/dev/input/event0", "Sleep Button", {ecodes.KEY_SLEEP})
    _patch_devices(mocker, [other])

    try:
        _listener()._find_keyboard()
    except RuntimeError as exc:
        assert "No keyboard device" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when no device exposes the key")


def test_works_for_modifier_hotkeys(mocker):
    """right_alt selection must also land on the real keyboard."""
    virtual = _FakeDevice("/dev/input/event16", "ydotoold virtual device", _FULL_KEYBOARD)
    real = _FakeDevice("/dev/input/event3", "AT Translated Set 2 keyboard", _FULL_KEYBOARD)
    _patch_devices(mocker, [virtual, real])

    chosen = _listener(key_code=ecodes.KEY_RIGHTALT)._find_keyboard()

    assert chosen.name == "AT Translated Set 2 keyboard"


def test_listens_on_all_real_keyboards(mocker):
    """Laptop built-in + external USB keyboard: BOTH must be watched so the
    hotkey fires whichever one the user types on (the root cause of a hotkey
    that works on one keyboard but not the other). The virtual injector device
    is still excluded."""
    keys = _FULL_KEYBOARD | {ecodes.KEY_RIGHTCTRL}
    laptop = _FakeDevice("/dev/input/event3", "AT Translated Set 2 keyboard", keys)
    usb = _FakeDevice("/dev/input/event17", "Logitech USB Keyboard", keys)
    virtual = _FakeDevice("/dev/input/event16", "ydotoold virtual device", keys)
    _patch_devices(mocker, [usb, virtual, laptop])

    chosen = _listener(key_code=ecodes.KEY_RIGHTCTRL)._find_keyboards()

    names = {d.name for d in chosen}
    assert names == {"AT Translated Set 2 keyboard", "Logitech USB Keyboard"}


def test_find_keyboards_excludes_partial_blocks_when_full_exists(mocker):
    """A partial hotkey block that happens to expose the key is dropped when a
    real full keyboard is present, so it can't spuriously fire."""
    full = _FakeDevice(
        "/dev/input/event3",
        "AT Translated Set 2 keyboard",
        _FULL_KEYBOARD | {ecodes.KEY_RIGHTCTRL},
    )
    block = _FakeDevice("/dev/input/event8", "ThinkPad Extra Buttons", {ecodes.KEY_RIGHTCTRL})
    _patch_devices(mocker, [full, block])

    chosen = _listener(key_code=ecodes.KEY_RIGHTCTRL)._find_keyboards()

    assert [d.name for d in chosen] == ["AT Translated Set 2 keyboard"]
