"""The Windows tray must obey the shared icon policy, not a private one.

`platform/windows/tray.py` used to keep its own seven-entry colour table keyed on
`TrayState`, bypassing `tray/menu.py::icon_spec` entirely. Three consequences,
all of which shipped:

* Windows showed different colours from Linux for the same daemon state.
* It had no command-mode purple and no "no text target" yellow at all, so the two
  states the colour scheme exists to warn about were invisible.
* Five of the twelve `TrayState` members were absent from the table and silently
  rendered as idle blue — including `MEETING`, which is an active capture.

The module imports only stdlib plus `platform.base` and `tray.*` at module
scope (pystray and Pillow are imported inside the functions), so this runs on
the Linux CI leg where the suite actually executes.
"""

from __future__ import annotations

import pytest

from yazses.platform.base import TrayModel, TrayState
from yazses.platform.windows import tray as win_tray
from yazses.tray.menu import icon_spec, status_from_model

# The five colours the shared policy can produce.
_BLUE, _GREEN, _YELLOW, _PURPLE, _RED = (
    "#1a73e8",
    "#34a853",
    "#fbbc04",
    "#9c27b0",
    "#e53935",
)


def _color(model: TrayModel) -> str:
    return icon_spec(status_from_model(model))[0]


def test_no_private_colour_table_remains() -> None:
    """Stops the bypass being reintroduced under a new name."""
    assert not hasattr(win_tray, "_GLYPH_COLOR")


@pytest.mark.parametrize("state", list(TrayState))
def test_every_tray_state_resolves_to_a_brand_colour(state: TrayState) -> None:
    assert _color(TrayModel(state=state)) in {_BLUE, _GREEN, _YELLOW, _PURPLE, _RED}


@pytest.mark.parametrize(
    "state",
    [
        TrayState.READBACK,
        TrayState.REMOTE_SETUP,
        TrayState.REMOTE_ACTIVE,
        TrayState.ENROLLING,
    ],
)
def test_the_formerly_orphaned_states_are_blue_by_rule(state: TrayState) -> None:
    """These four fell through the old table by accident; now they do so by policy."""
    assert _color(TrayModel(state=state)) == _BLUE


def test_meeting_capture_is_green_not_idle() -> None:
    """Meeting Mode captures audio, so it must not read as idle."""
    assert _color(TrayModel(state=TrayState.MEETING)) == _GREEN


def test_command_mode_is_purple() -> None:
    """Windows never had this state; it is the whole point of the command key."""
    model = TrayModel(state=TrayState.RECORDING, command_mode=True)
    assert _color(model) == _PURPLE


def test_dictating_with_no_text_target_is_yellow() -> None:
    model = TrayModel(state=TrayState.RECORDING, target_ok=False)
    assert _color(model) == _YELLOW


def test_a_silent_streak_is_red() -> None:
    assert _color(TrayModel(state=TrayState.IDLE, silent_streak=5)) == _RED


def test_status_from_model_carries_the_pinned_mic_into_the_tooltip() -> None:
    """`input_device` had no field on TrayModel, so every tray said "Mic: default"."""
    model = TrayModel(state=TrayState.IDLE, input_device="Blue Yeti", hotkey="ctrl")
    _, tooltip = icon_spec(status_from_model(model))
    assert "Mic: Blue Yeti" in tooltip


def test_linux_and_windows_derive_identical_status() -> None:
    """Both trays go through the same bridge, so parity is structural."""
    from yazses.platform.linux import tray as linux_tray

    models = [
        TrayModel(state=TrayState.IDLE),
        TrayModel(state=TrayState.RECORDING, command_mode=True),
        TrayModel(state=TrayState.RECORDING, target_ok=False),
        TrayModel(state=TrayState.ERROR, silent_streak=4),
        TrayModel(state=TrayState.MEETING, input_device="Yeti", hotkey="alt"),
    ]
    lin = linux_tray.LinuxTray()
    for model in models:
        lin.set_state(model)  # no Qt bridge yet, so it only stashes the dict
        assert lin._latest == status_from_model(model)


def test_tooltip_is_capped_to_the_shell_limit() -> None:
    """Shell_NotifyIcon's szTip truncates silently at 128 wide chars."""
    model = TrayModel(
        state=TrayState.RECORDING,
        command_mode=True,
        silent_streak=9,
        hotkey="ctrl+alt+shift",
        input_device="A Very Long USB Audio Capture Device Name From A Monitor",
    )
    _, tooltip = icon_spec(status_from_model(model))
    assert len(tooltip[: win_tray._TOOLTIP_MAX]) <= 127


def test_the_glyph_is_the_brand_mark_not_a_bare_disc() -> None:
    """The user-visible half of the fix: a badge with a "Y", anti-aliased."""
    pytest.importorskip("PIL", reason="Pillow is a dev/win32 dependency")

    img = win_tray._make_icon(_BLUE)
    assert img.size == (win_tray._ICON_PX, win_tray._ICON_PX)
    assert img.mode == "RGBA"
    px = img.load()
    # A disc leaves the corners transparent too, so prove the mark is there: the
    # centre must be the "Y", which a solid-colour disc never has.
    #
    # Asserted as *contrast against the badge* rather than as white. The glyph is
    # no longer always white: on the yellow "nowhere to type" badge a white mark
    # measures 1.71:1 and is unreadable, so `tray/menu.py::glyph_for` picks black
    # there. Pinning the colour would pin the defect.
    from yazses.settingsui.theme import AA_NORMAL, contrast_ratio

    mid = win_tray._ICON_PX // 2
    badge = tuple(int(_BLUE.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    assert contrast_ratio(px[mid, mid][:3], badge) >= AA_NORMAL
    assert px[0, 0][3] == 0
