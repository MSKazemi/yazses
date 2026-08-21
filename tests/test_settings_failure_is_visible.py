"""When the settings window refuses to open, the reason must reach the user.

The reported Windows symptom was that the tray's "Settings…" entry did nothing at
all. Three things lined up to produce silence, and only the first is a missing
feature — the other two are working code reporting into a void:

1. the frozen bundle shipped no Qt (see `test_frozen_bundles_ship_the_gui.py`);
2. `settingsui.app.run` explained itself on **stderr**, and a windowed Windows
   binary has no console — `wincon.ensure_streams` binds stderr to `os.devnull` so
   writes do not raise, which makes them vanish;
3. `TrayController.launch_settings` returns True as soon as `Popen` succeeds, so
   the tray believed the window had opened and reported nothing.

`ensure_streams()` already returned whether output would be visible. That answer was
discarded at the call site — the bug was not a missing capability but an unread one.
"""
from __future__ import annotations

import sys

import pytest

from yazses.system import wincon


def test_alert_is_a_no_op_off_windows():
    """It must be safe to call unconditionally; the platform check lives inside."""
    assert wincon.alert("message", "title") is False


def test_alert_never_raises_even_if_the_call_blows_up(monkeypatch):
    """A missing message box must not replace the fault it was reporting."""
    monkeypatch.setattr(sys, "platform", "win32")

    class _Boom:
        def __getattr__(self, _name):  # ctypes.windll.user32 -> explode
            raise OSError("no user32 here")

    import ctypes

    monkeypatch.setattr(ctypes, "windll", _Boom(), raising=False)
    assert wincon.alert("message", "title") is False


def test_ensure_streams_reports_visibility_and_the_caller_reads_it():
    """Guards the actual regression: the return value must not be discarded again."""
    import inspect

    from yazses.settingsui import app

    src = inspect.getsource(app.run)
    assert "ensure_streams()" in src, "the streams fixup is gone"
    assert "= ensure_streams()" in src, (
        "settingsui.app.run calls ensure_streams() and throws away the answer. That "
        "value is how it knows whether stderr is visible; without it, every reason "
        "the window cannot open is printed into os.devnull — which is exactly the "
        "Windows bug where clicking Settings did nothing and said nothing."
    )
    assert "alert(" in src, (
        "no visible fallback: when the console is not visible the reason must reach "
        "a surface the user can actually see"
    )


@pytest.mark.parametrize("symbol", ["_MISSING_PYSIDE_MSG", "_NO_DISPLAY_MSG"])
def test_the_refusal_messages_still_exist(symbol):
    """They are the payload; a rename must not silently empty the dialog."""
    from yazses.settingsui import app

    assert getattr(app, symbol).strip(), f"{symbol} is empty"
