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


def test_alert_is_a_no_op_off_windows(monkeypatch):
    """It must be safe to call unconditionally; the platform check lives inside.

    The platform is *forced* rather than read off the host, and that is the whole
    point of the test. Read off the host it asserts nothing on Linux (the guard is
    trivially true) and on Windows it does not assert either -- it calls the real
    `MessageBoxW`, which is modal and synchronous: it returns the button the user
    clicked, so with nobody at the machine it never returns at all.

    That is not a hypothesis. Four Windows CI jobs -- runs 32661049814 and
    32661231351, Python 3.11 and 3.12 alike -- printed this test's name and then
    nothing for 2 h 30 m, while their Linux and macOS siblings finished in ten
    minutes:

        19:25:38  ...test_the_settings_model_reads_all_four_from_the_config PASSED [85%]
        21:56:09  ...test_alert_is_a_no_op_off_windows
        21:56:09  ##[error]The operation was canceled.

    A hang is not a failure. CI produced no result rather than a red one, which is
    why this survived every Windows run the suite has ever had -- and why it only
    became visible now: until the liveness-probe crash at 49% was fixed, the run
    died before it ever got here.
    """
    monkeypatch.setattr(sys, "platform", "linux")
    assert wincon.alert("message", "title") is False


def test_alert_shows_a_box_on_windows_and_says_so():
    """The other half of the guard: on Windows it must actually call user32.

    Nothing covered the success path, so `alert` could have degraded to a
    permanent `return False` -- the void it exists to escape -- and stayed green.
    A recording double stands in for `windll` because the real call blocks.
    """
    calls: list[tuple] = []

    class _User32:
        def MessageBoxW(self, *args):  # noqa: N802 -- the Win32 spelling
            calls.append(args)
            return 1

    class _Windll:
        user32 = _User32()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, "platform", "win32")
        import ctypes

        mp.setattr(ctypes, "windll", _Windll(), raising=False)
        assert wincon.alert("body", "head") is True

    assert calls == [(None, "body", "head", wincon._MB_FLAGS)]


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
