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


def test_icon_spec_command_mode_is_purple():
    _PURPLE, _GREEN = "#9c27b0", "#34a853"
    # Holding the command key (command mode) → purple, distinct from green dictation.
    assert icon_spec({"state": "recording", "command_mode": True})[0] == _PURPLE
    # Command mode wins over the no-text-target yellow (commands don't type text).
    assert icon_spec({"state": "recording", "command_mode": True, "target_ok": False})[0] == _PURPLE
    # Not in command mode → normal dictation green.
    assert icon_spec({"state": "recording", "command_mode": False})[0] == _GREEN
    # command_mode only matters while recording (ignored when idle).
    assert icon_spec({"state": "idle", "command_mode": True})[0] == "#1a73e8"


def test_icon_spec_state_colors():
    _GREEN, _YELLOW, _BLUE, _RED = "#34a853", "#fbbc04", "#1a73e8", "#e53935"
    # Recording into a text field → green.
    assert icon_spec({"state": "recording"})[0] == _GREEN
    assert icon_spec({"state": "recording", "target_ok": True})[0] == _GREEN
    assert icon_spec({"state": "transcribing"})[0] == _GREEN
    assert icon_spec({"state": "injecting"})[0] == _GREEN
    assert icon_spec({"state": "meeting"})[0] == _GREEN
    # Recording with NO text field focused → yellow (unknown stays green, no false alarm).
    assert icon_spec({"state": "recording", "target_ok": False})[0] == _YELLOW
    assert icon_spec({"state": "recording", "target_ok": None})[0] == _GREEN
    # Normal / ready / idle → blue (target_ok irrelevant when not recording).
    assert icon_spec({"state": "idle"})[0] == _BLUE
    assert icon_spec({"state": "idle", "target_ok": False})[0] == _BLUE
    assert icon_spec({"state": "loading"})[0] == _BLUE
    assert icon_spec({"state": "paused"})[0] == _BLUE
    # Problems → red, overriding recording/target. A streak only counts as a problem
    # once it reaches the daemon's own silent_streak_threshold.
    assert icon_spec({"state": "recording", "silent_streak": 2,
                      "silent_streak_threshold": 2})[0] == _RED
    assert icon_spec({"state": "recording", "target_ok": False, "silent_streak": 1,
                      "silent_streak_threshold": 1})[0] == _RED
    assert icon_spec({"state": "error"})[0] == _RED


def test_icon_spec_tolerates_one_silent_clip():
    """A single discarded clip is ordinary — a brushed hotkey, or a hold with no speech.

    Regression: the icon went red at the first silent clip and stayed red until the next
    successful dictation, reporting a working daemon as faulty. The daemon itself only
    treats a streak as trouble at `[audio] silent_streak_threshold` (default 3).
    """
    _BLUE, _RED = "#1a73e8", "#e53935"
    status = {"state": "idle", "silent_streak": 1, "silent_streak_threshold": 3}

    assert icon_spec(status)[0] == _BLUE
    assert icon_spec({**status, "silent_streak": 2})[0] == _BLUE
    assert icon_spec({**status, "silent_streak": 3})[0] == _RED


def test_icon_spec_falls_back_to_the_config_default_threshold():
    """An older daemon omits the key; don't fall back to alarming at one."""
    _BLUE, _RED = "#1a73e8", "#e53935"

    assert icon_spec({"state": "idle", "silent_streak": 1})[0] == _BLUE
    assert icon_spec({"state": "idle", "silent_streak": 3})[0] == _RED
    # A nonsensical threshold must not disable the red state entirely.
    assert icon_spec({"state": "idle", "silent_streak": 3,
                      "silent_streak_threshold": 0})[0] == _RED
    assert icon_spec({"state": "idle", "silent_streak": 3,
                      "silent_streak_threshold": "oops"})[0] == _RED


def test_icon_spec_tooltip_has_mic_and_hotkey():
    _, tip = icon_spec({"state": "idle", "input_device": "mymic", "hotkey": "right_ctrl"})
    assert "mymic" in tip and "right_ctrl" in tip and "idle" in tip
