"""Whether the settings window can open at all (mirrors ``tray/launch.py``).

Pure, so ``app.py`` stays a thin Qt shell and both gates unit-test without a
display. Qt does not degrade politely: constructing a ``QApplication`` with no
platform plugin available calls ``abort()``, which over SSH means SIGABRT and a
plugin dump instead of a sentence the user can act on.
"""
from __future__ import annotations

from collections.abc import Mapping


def has_display(env: Mapping[str, str], *, platform: str | None = None) -> bool:
    """Whether a graphical session is present, so the window has somewhere to open.

    Delegates to :func:`yazses.system.graphical.has_graphical_session`. This used to
    test ``DISPLAY``/``WAYLAND_DISPLAY`` directly, which is an X11/Wayland question:
    Windows and macOS set neither, so the Settings window refused to open on both,
    and said so by printing to a console a windowed binary does not have.
    """
    from yazses.system.graphical import has_graphical_session

    return has_graphical_session(env, platform=platform)


def pyside_available() -> bool:
    """Whether PySide6 is importable (a base dep, but optional on old distros)."""
    import importlib.util

    return importlib.util.find_spec("PySide6") is not None
