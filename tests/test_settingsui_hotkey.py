"""Changing the hold-to-talk key from the settings window (#62).

Requested directly: *"I need to have the change hotkeys in the GUI also in
setting"*. Until now the window offered feature checkboxes and nothing else, so
the key you hold to dictate — the single most personal setting in the
application — could only be changed by typing a command or editing TOML.

The validation was already written and already tested (`controls.validate_hotkey`),
and had no caller. What was missing is a controller method between it and Qt.

The rule it enforces is worth stating plainly, because it is the reason this is
not a free-text box: **a key the platform cannot bind leaves the user unable to
dictate, with nothing on screen explaining why.** So the window refuses before
writing, rather than writing and letting the daemon fail at the next start.
"""
from __future__ import annotations

import pytest

from yazses.settingsui.controller import SettingsController


class _Cfg:
    """Enough Config for the hotkey path."""

    class _Hotkey:
        key = "right_ctrl"
        command_key = ""

    hotkey = _Hotkey()


def _controller(writes: list | None = None) -> SettingsController:
    sink = writes if writes is not None else []

    def _write(section: str, key: str, value: object, quote: bool | None) -> None:
        sink.append((section, key, value))

    return SettingsController(lambda: _Cfg(), _write)


def test_setting_a_supported_key_writes_it() -> None:
    writes: list = []
    result = _controller(writes).set_hotkey("left_alt")
    assert result.ok, result.error
    assert writes == [("hotkey", "key", "left_alt")]


def test_an_unbindable_key_is_refused_before_anything_is_written() -> None:
    """The failure this prevents is silent: a bad key writes fine and then the
    daemon simply never responds to the key you press."""
    writes: list = []
    result = _controller(writes).set_hotkey("f13")
    assert not result.ok
    assert "f13" in (result.error or "")
    assert writes == [], "a rejected key must not reach the config file"


def test_the_macos_spelling_is_accepted() -> None:
    """`right_option` is the name a Mac user reaches for; every backend binds it."""
    writes: list = []
    assert _controller(writes).set_hotkey("right_option").ok
    assert writes == [("hotkey", "key", "right_option")]


def test_whitespace_and_case_are_forgiven() -> None:
    writes: list = []
    assert _controller(writes).set_hotkey("  Right_Alt \n").ok
    assert writes == [("hotkey", "key", "right_alt")]


def test_an_empty_key_is_refused_with_a_readable_reason() -> None:
    result = _controller().set_hotkey("")
    assert not result.ok
    assert result.error


def test_clashing_with_the_command_key_is_refused() -> None:
    """Both keys on one physical key means command mode swallows every dictation.

    Aliases make this easy to hit by accident: `right_option` and `right_alt` are
    the same key under two names, so a string comparison would miss it. (I did
    exactly this to my own config while testing.)
    """
    class _Clash(_Cfg):
        class _Hotkey:
            key = "right_ctrl"
            command_key = "right_alt"
        hotkey = _Hotkey()

    writes: list = []

    def _write(section, key, value, quote):  # noqa: ANN001
        writes.append((section, key, value))

    ctrl = SettingsController(lambda: _Clash(), _write)
    result = ctrl.set_hotkey("right_option")
    assert not result.ok
    assert "command" in (result.error or "").lower()
    assert writes == []


def test_a_write_failure_is_reported_not_raised() -> None:
    def _boom(section, key, value, quote):  # noqa: ANN001
        raise OSError("read-only file system")

    result = SettingsController(lambda: _Cfg(), _boom).set_hotkey("space")
    assert not result.ok
    assert "read-only" in (result.error or "")


def test_the_model_carries_the_current_key_for_the_picker() -> None:
    """The window has to show what is set now, or the picker opens on a lie."""
    from yazses.config import Config
    from yazses.settingsui.model import build_settings_model

    cfg = Config()
    model = build_settings_model(cfg)
    assert model.hotkey == cfg.hotkey.key


@pytest.mark.parametrize("key", ["right_alt", "space", "left_meta"])
def test_every_offered_key_is_accepted_by_the_controller(key: str) -> None:
    """The picker's list and the controller's validation must not disagree."""
    assert _controller().set_hotkey(key).ok
