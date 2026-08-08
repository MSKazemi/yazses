"""Whether the settings window can open at all (mirrors ``tray/launch.py``).

Pure, so ``app.py`` stays a thin Qt shell and both gates unit-test without a
display. Qt does not degrade politely: constructing a ``QApplication`` with no
platform plugin available calls ``abort()``, which over SSH means SIGABRT and a
plugin dump instead of a sentence the user can act on.
"""
from __future__ import annotations

from collections.abc import Mapping


def has_display(env: Mapping[str, str]) -> bool:
    """Whether a graphical session is present (``DISPLAY`` for X11, or Wayland).

    ``QT_QPA_PLATFORM`` is honoured too: an explicit platform (``offscreen``,
    ``vnc``, ``minimal``, …) means the caller knows what they are doing — that is
    how the headless smoke tests drive the window.
    """
    if env.get("QT_QPA_PLATFORM"):
        return True
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def pyside_available() -> bool:
    """Whether PySide6 is importable (a base dep, but optional on old distros)."""
    import importlib.util

    return importlib.util.find_spec("PySide6") is not None
