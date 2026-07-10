"""Desktop window control for look-to-pane routing (X11 via xdotool).

Glance-Type needs three things the pure logic can't do on its own: the screen
size (to place calibration targets), the list of top-level windows with their
bounding boxes (to find the one under the gaze point), and the ability to focus
a window (so the next dictation types into it). On X11 all three come from
``xdotool``; ``build_desktop`` returns ``None`` off X11 or when xdotool is absent,
so the daemon degrades to focus-only and never crashes (ADR-011 dormancy).

Wayland compositors forbid an external process from focusing arbitrary windows,
so this backend is X11-only by design — the documented OS limitation for gaze.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from typing import Callable, Protocol, runtime_checkable

log = logging.getLogger(__name__)

# (id, x, y, w, h) — a top-level window's bounding box in screen pixels.
Window = tuple[int, int, int, int, int]


@runtime_checkable
class DesktopBackend(Protocol):
    """Minimal window control needed to route a dictation to a screen region."""

    def screen_size(self) -> tuple[int, int]:
        """Return the primary display size ``(width, height)`` in pixels."""
        ...

    def list_windows(self) -> list[Window]:
        """Return visible top-level windows as ``(id, x, y, w, h)``, front-to-back."""
        ...

    def focused_window(self) -> int | None:
        """Return the id of the currently focused window, or None."""
        ...

    def activate(self, window_id) -> None:
        """Raise and focus ``window_id`` so subsequent typing lands in it."""
        ...


class XdotoolDesktop:
    """``DesktopBackend`` over the ``xdotool`` CLI (X11)."""

    def __init__(self, runner: Callable[[list[str]], str] | None = None) -> None:
        self._run = runner or self._default_runner

    @staticmethod
    def _default_runner(argv: list[str]) -> str:
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=2.0, check=True
        ).stdout

    def screen_size(self) -> tuple[int, int]:
        out = self._run(["xdotool", "getdisplaygeometry"]).split()
        return (int(out[0]), int(out[1]))

    def list_windows(self) -> list[Window]:
        out = self._run(["xdotool", "search", "--onlyvisible", "--name", ""])
        try:
            screen_w, screen_h = self.screen_size()
        except Exception:
            screen_w = screen_h = 0
        windows: list[Window] = []
        for line in out.splitlines():
            line = line.strip()
            if not line.isdigit():
                continue
            geo = self._geometry(int(line))
            if geo is None:
                continue
            if self._is_fullscreen_container(geo, screen_w, screen_h):
                # The desktop/root window spans the whole screen and would shadow
                # every real window in window_at_point — never a gaze target.
                continue
            windows.append(geo)
        return windows

    @staticmethod
    def _is_fullscreen_container(geo: Window, screen_w: int, screen_h: int) -> bool:
        """True for a window covering (almost) the whole screen at the origin.

        That is the desktop/root (or a lone maximised window); routing gaze to it
        is meaningless because it fills every zone. Dropping it lets the smallest
        real window under the gaze point win. No-op when the screen size is
        unknown (screen_w/h == 0).
        """
        if not screen_w or not screen_h:
            return False
        _wid, wx, wy, ww, wh = geo
        return wx <= 0 and wy <= 0 and ww >= screen_w * 0.98 and wh >= screen_h * 0.98

    def _geometry(self, wid: int) -> Window | None:
        try:
            out = self._run(["xdotool", "getwindowgeometry", str(wid)])
        except Exception:
            return None
        pos = re.search(r"Position:\s*(-?\d+),(-?\d+)", out)
        size = re.search(r"Geometry:\s*(\d+)x(\d+)", out)
        if not pos or not size:
            return None
        return (wid, int(pos.group(1)), int(pos.group(2)), int(size.group(1)), int(size.group(2)))

    def focused_window(self) -> int | None:
        try:
            out = self._run(["xdotool", "getwindowfocus"]).strip()
        except Exception:
            return None
        return int(out) if out.isdigit() else None

    def activate(self, window_id) -> None:
        self._run(["xdotool", "windowactivate", str(window_id)])


def build_desktop() -> DesktopBackend | None:
    """Return an X11 desktop backend, or ``None`` when unavailable/unsupported.

    None when not an X11 session or ``xdotool`` is not installed — callers then
    skip gaze routing and dictation stays on the focused window.
    """
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session and session != "x11":
        log.info("Gaze routing needs X11 (session=%r); look-to-pane dormant.", session)
        return None
    if shutil.which("xdotool") is None:
        log.info("Gaze routing needs xdotool; not found. Look-to-pane dormant.")
        return None
    return XdotoolDesktop()
