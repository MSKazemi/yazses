"""Turn a :class:`WmAction` into xdotool argv — pure (ADR-v2-070, #164).

``windowctl/commands.py`` has parsed "move window left half" into a ``WmAction``
since ADR-v2-070 and nothing ever executed one: the ``WindowBackend`` protocol
offered ``list_windows()`` and ``focus()``, and there was no method that could carry
a layout action out. So the feature enabled cleanly and the examples it printed did
nothing — the defect ``tests/test_windowctl_promises.py`` was written to pin down.

This module is the missing half, kept pure for the same reason the grammar is: the
interesting part is the arithmetic (which rectangle is "the left half" of a screen
with a panel on it?) and the ordering (a maximized window ignores a move until it is
un-maximized), and neither needs a display to test.

**xdotool only, deliberately.** ``wmctrl`` is the more usual tool for this and would
add a second binary to check for, a second thing to install, and a second failure
mode; ``build_window_backend`` already requires xdotool and refuses without it.
Everything here is expressible in xdotool ≥ 3.0: ``windowstate`` (2015), ``windowsize``,
``windowmove``, ``windowminimize``, ``windowclose``, ``set_desktop``, ``get_desktop``.

Two decisions worth writing down because they are not recoverable from the code:

* **A snap un-maximizes first.** ``windowmove`` on a maximized window is accepted and
  then ignored by the window manager, so the sequence would report success and do
  nothing — the exact failure this whole feature already had once, one layer down.
* **Spoken workspace numbers are 1-based, xdotool's are 0-based.** "Workspace 3"
  means the third one to the person saying it. Getting this wrong is invisible in a
  unit test that asserts the number it passed in, so ``plan`` subtracts and the test
  asserts the *translated* value.
"""
from __future__ import annotations

from dataclasses import dataclass

from yazses.windowctl.commands import WmAction

#: Fractions of the screen a snap target occupies: (x, y, w, h), each 0..1.
_SNAP_RECTS: dict[str, tuple[float, float, float, float]] = {
    "left":         (0.0, 0.0, 0.5, 1.0),
    "right":        (0.5, 0.0, 0.5, 1.0),
    "top":          (0.0, 0.0, 1.0, 0.5),
    "bottom":       (0.0, 0.5, 1.0, 0.5),
    "top-left":     (0.0, 0.0, 0.5, 0.5),
    "top-right":    (0.5, 0.0, 0.5, 0.5),
    "bottom-left":  (0.0, 0.5, 0.5, 0.5),
    "bottom-right": (0.5, 0.5, 0.5, 0.5),
}

#: Both maximize axes, as xdotool spells them.
_MAX_STATES = ("MAXIMIZED_VERT", "MAXIMIZED_HORZ")


@dataclass(frozen=True)
class Screen:
    """Usable screen area in pixels, as `xdotool getdisplaygeometry` reports it."""

    width: int
    height: int


class UnsupportedAction(ValueError):
    """A WmAction this planner cannot express. Raised, never silently ignored.

    A layout verb that quietly does nothing is the original defect. If the grammar
    ever learns a kind the planner does not know, the caller must be able to say so
    rather than return success.
    """


def _unmaximize(window: str) -> list[str]:
    args = ["xdotool", "windowstate"]
    for state in _MAX_STATES:
        args += ["--remove", state]
    return [*args, window]


def snap_rect(target: str, screen: Screen) -> tuple[int, int, int, int]:
    """The pixel rectangle for a snap target. Pure arithmetic, so it is testable.

    Computed from the two **edges**, not from an origin plus an independently
    rounded size. On an odd-width screen the latter loses a pixel: ``round(0.5 *
    1921)`` is 960 for both the origin and the width, so the right half spans
    960..1920 and leaves a one-pixel strip of desktop showing at the screen edge.
    Deriving the width as ``right_edge - left_edge`` makes the halves tile exactly
    at any resolution, which is the property worth having — a persistent sliver
    along one edge looks like a rendering bug and gets reported as one.
    """
    if target not in _SNAP_RECTS:
        raise UnsupportedAction(f"unknown snap target: {target!r}")
    fx, fy, fw, fh = _SNAP_RECTS[target]
    x = round(fx * screen.width)
    y = round(fy * screen.height)
    w = round((fx + fw) * screen.width) - x
    h = round((fy + fh) * screen.height) - y
    return x, y, w, h


def plan(
    action: WmAction,
    window: str,
    screen: Screen | None = None,
    current_desktop: int | None = None,
) -> list[list[str]]:
    """The xdotool commands that carry out ``action``, in order.

    ``window`` is an X window id. ``screen`` is required for the actions that need
    geometry (``snap``, ``center``); ``current_desktop`` for ``workspace_rel``.
    Both raise :class:`UnsupportedAction` when missing rather than guessing — a
    guessed screen size moves the window somewhere arbitrary.
    """
    kind = action.kind

    if kind == "snap":
        if screen is None:
            raise UnsupportedAction("snap needs the screen geometry")
        x, y, w, h = snap_rect(str(action.arg), screen)
        return [
            _unmaximize(window),
            ["xdotool", "windowsize", window, str(w), str(h)],
            ["xdotool", "windowmove", window, str(x), str(y)],
        ]

    if kind == "center":
        if screen is None:
            raise UnsupportedAction("center needs the screen geometry")
        # Half the screen, centred: "center" with the current size is a no-op for an
        # already-maximized window, which is the state it is most often said from.
        w = round(screen.width * 0.5)
        h = round(screen.height * 0.5)
        return [
            _unmaximize(window),
            ["xdotool", "windowsize", window, str(w), str(h)],
            ["xdotool", "windowmove", window,
             str(round((screen.width - w) / 2)), str(round((screen.height - h) / 2))],
        ]

    if kind == "maximize":
        args = ["xdotool", "windowstate"]
        for state in _MAX_STATES:
            args += ["--add", state]
        return [[*args, window]]

    if kind == "minimize":
        return [["xdotool", "windowminimize", window]]

    if kind == "fullscreen":
        return [["xdotool", "windowstate", "--toggle", "FULLSCREEN", window]]

    if kind == "close":
        # `windowclose` asks politely (WM_DELETE_WINDOW), so an editor with unsaved
        # work still gets to prompt. `windowkill` would not, and a misheard "close
        # the window" must not be able to destroy work.
        return [["xdotool", "windowclose", window]]

    if kind == "workspace":
        spoken = int(str(action.arg if action.arg is not None else 1))
        if spoken < 1:
            raise UnsupportedAction(f"workspace numbers start at 1, got {spoken}")
        return [["xdotool", "set_desktop", str(spoken - 1)]]

    if kind == "workspace_rel":
        if current_desktop is None:
            raise UnsupportedAction("relative workspace needs the current desktop")
        target = current_desktop + int(str(action.arg if action.arg is not None else 0))
        # Clamp at the low end only: the high end needs the desktop count, and
        # xdotool already refuses an out-of-range desktop without side effects.
        return [["xdotool", "set_desktop", str(max(0, target))]]

    raise UnsupportedAction(f"no plan for WmAction kind {kind!r}")
