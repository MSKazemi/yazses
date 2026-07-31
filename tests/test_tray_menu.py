"""Pure tray menu + icon model (no Qt, no hardware)."""
from yazses.audio.devices import InputDevice
from yazses.tray.menu import build_menu_model, icon_spec


def _devs():
    return [
        InputDevice(1, "AT Translated Set 2 keyboard", 2),
        InputDevice(7, "USB PnP Audio Device", 1),
        InputDevice(11, "default", 32, is_default=True),
    ]


def test_menu_header_and_mic_line():
    m = build_menu_model({"state": "idle", "input_device": "default"}, _devs(), "")
    assert m.header == "YazSes — idle"
    assert m.mic_line == "Mic: default"
    assert m.warning is None


def test_menu_silent_streak_warning():
    m = build_menu_model({"state": "idle", "silent_streak": 3}, _devs(), "")
    assert m.warning == "⚠ 3 silent clips in a row"
    m1 = build_menu_model({"silent_streak": 1}, _devs(), "")
    assert m1.warning == "⚠ 1 silent clip in a row"


def test_menu_unpinned_checks_follow_default():
    m = build_menu_model({}, _devs(), "")
    follow = m.devices[0]
    assert follow.label == "Follow OS default" and follow.device == "" and follow.checked
    assert not any(d.checked for d in m.devices[1:])


def test_menu_pinned_device_is_checked():
    m = build_menu_model({}, _devs(), "USB")
    follow = m.devices[0]
    assert not follow.checked
    usb = next(d for d in m.devices if d.device == "USB PnP Audio Device")
    assert usb.checked
    # Exactly one device (besides follow) is checked.
    assert sum(d.checked for d in m.devices) == 1


def test_menu_marks_os_default_label():
    m = build_menu_model({}, _devs(), "")
    labels = [d.label for d in m.devices]
    assert any("(OS default)" in lbl for lbl in labels)


def test_icon_spec_state_colors():
    _BLUE, _RED = "#1a73e8", "#e53935"
    # Actively working → blue.
    assert icon_spec({"state": "recording"})[0] == _BLUE
    assert icon_spec({"state": "transcribing"})[0] == _BLUE
    assert icon_spec({"state": "injecting"})[0] == _BLUE
    # Idle / loading / paused → reddish.
    assert icon_spec({"state": "idle"})[0] == _RED
    assert icon_spec({"state": "loading"})[0] == _RED
    # Problems → reddish, overriding any state.
    assert icon_spec({"state": "recording", "silent_streak": 2})[0] == _RED
    assert icon_spec({"state": "error"})[0] == _RED


def test_icon_spec_tooltip_has_mic_and_hotkey():
    _, tip = icon_spec({"state": "idle", "input_device": "mymic", "hotkey": "right_ctrl"})
    assert "mymic" in tip and "right_ctrl" in tip and "idle" in tip
