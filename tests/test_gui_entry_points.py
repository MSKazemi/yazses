"""Windowed programs must be declared — and survive — as GUI scripts.

On Windows, pip builds a *console* launcher for `[project.scripts]` and a
pythonw launcher for `[project.gui-scripts]`. All six entry points were in the
first table, so a console window sat behind the tray, the settings window and
the overlay — and appeared at every login, because Windows autostart runs
`yazses-tray.exe` (platform/windows/lifecycle.py).

Moving them is only safe because a GUI launcher has no console at all:
`sys.stderr` is None, and `logging.basicConfig()` binds the stream when the
handler is constructed, so it raises on the first log line. That is the same
failure that crashed `yazses doctor`, and it must not be reintroduced here.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

# run() functions that will have no console on Windows.
_GUI_MODULES = [
    ("yazses.tray.app", "yazses-tray"),
    ("yazses.settingsui.app", "yazses-settings"),
    ("yazses.overlay.app", "yazses-overlay"),
]


def _tables() -> tuple[dict, dict]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return data["project"].get("scripts", {}), data["project"].get("gui-scripts", {})


def test_windowed_programs_are_gui_scripts():
    console, gui = _tables()
    for _module, script in _GUI_MODULES:
        assert script in gui, f"{script} is windowed; a console launcher flashes a window"
        assert script not in console, f"{script} must not be in both tables"


def test_terminal_programs_stay_console_scripts():
    """The inverse mistake would be worse: a GUI launcher for the CLI has
    nowhere to print, which is exactly what made `yazses doctor` silent."""
    console, gui = _tables()
    for script in ("yazses", "yazses-daemon", "yazses-agent"):
        assert script in console, f"{script} needs a console to print to"
        assert script not in gui


def test_every_entry_point_is_declared_exactly_once():
    console, gui = _tables()
    overlap = set(console) & set(gui)
    assert not overlap, f"declared in both tables: {sorted(overlap)}"


@pytest.mark.parametrize(("module", "_script"), _GUI_MODULES)
def test_gui_entry_point_survives_having_no_console(module, _script, monkeypatch):
    """The regression guard. With every stream detached — a GUI launcher on
    Windows — reaching logging.basicConfig() must not raise."""
    import importlib
    import logging

    mod = importlib.import_module(module)

    for name in ("stdout", "stderr", "stdin"):
        monkeypatch.setattr(sys, name, None)

    # Replace basicConfig with something that does the one thing that actually
    # crashes on a detached stream — build a StreamHandler and emit through it —
    # and then stop. A no-op stub would make this test pass against the very bug
    # it guards; running on past it would reach Qt, which is installed on some
    # CI legs and must never open a window here.
    class _Stop(Exception):
        pass

    def _probe(**_kw):
        logging.StreamHandler().emit(
            logging.LogRecord("t", logging.INFO, __file__, 0, "probe", None, None)
        )
        raise _Stop

    monkeypatch.setattr(logging, "basicConfig", _probe)

    # Reaching _Stop means ensure_streams() ran and logging survived it, which
    # is the whole assertion. An AttributeError on a None stream would not.
    with pytest.raises(_Stop):
        mod.run()

    # The streams must have been repaired rather than left as None.
    for name in ("stdout", "stderr", "stdin"):
        assert getattr(sys, name) is not None, f"sys.{name} left detached by {module}"
