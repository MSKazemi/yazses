"""Focus a window by name, spoken (#39).

`windowctl/commands.py` already parses layout commands (snap, maximize,
workspace). What it could not do is the thing people actually ask for first:
"focus the browser". That needs a backend that can *enumerate* windows with
their titles, and a matcher, because nobody says a window title exactly.

Two deliberate choices:

* **The matcher is `fileopen.match.fuzzy_rank`, not a new one.** Ranking a spoken
  query against a list of names is the same problem the file opener solved, and
  a second implementation would drift from it — the two would answer differently
  for the same words, which is exactly the sort of inconsistency a voice
  interface cannot afford.
* **Ambiguity refuses.** When two windows score alike, focusing the wrong one
  silently redirects everything the user types next. A refusal they can hear is
  cheaper than dictation landing in the wrong application.

X11 only, and honestly so. Wayland forbids one client focusing another's window;
there is no portal for it today, so `build_window_backend` returns None there and
`yazses doctor` says why rather than offering a feature that cannot work.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from yazses.fileopen.match import fuzzy_rank
from yazses.windowctl.actions import Screen, UnsupportedAction, plan
from yazses.windowctl.commands import WmAction

log = logging.getLogger(__name__)

# How far ahead the winner must be for the match to count as unambiguous.
# Two windows titled "notes.txt — gedit" and "notes.md — gedit" score almost
# identically, and picking either one is a coin flip the user did not ask for.
AMBIGUITY_MARGIN = 0.08
MATCH_THRESHOLD = 0.34


@dataclass(frozen=True)
class WindowRef:
    """A focusable top-level window."""

    id: str
    title: str


@runtime_checkable
class WindowBackend(Protocol):
    """Enumerate and focus top-level windows."""

    def list_windows(self) -> list[WindowRef]:
        """Visible top-level windows with their titles."""

    def focus(self, window_id: str) -> bool:
        """Raise and focus a window. True on success."""

    def perform(self, action: WmAction) -> bool:
        """Carry out a layout/workspace action on the active window.

        The half of this protocol that did not exist. `windowctl/commands.py` has
        parsed "move window left half" into a `WmAction` since ADR-v2-070 and there
        was no method here that could execute one, so `yazses features enable
        windowctl` succeeded and every layout example it printed did nothing.

        Takes the `WmAction` whole rather than one method per verb: the grammar can
        grow a kind without every backend having to grow a method it would only
        raise from, and `windowctl/actions.py` is the single place that decides what
        a kind means. False when the action could not be carried out — including
        when this backend does not support that kind.
        """


# ── grammar ──────────────────────────────────────────────────────────────────
#
# Anchored at both ends: "focus" and "switch to" appear in ordinary speech, and a
# suffix match would turn "I need to focus the browser" into a command instead of
# text. Same rule as commands/revise.py::_SCRATCH_RE.
_FOCUS_RE = re.compile(
    r"(?:focus|switch\s+to|go\s+to|activate|bring\s+up)\s+"
    r"(?:the\s+|my\s+)?(?P<target>.+?)"
    r"(?:\s+window)?",
    re.I,
)


def parse_focus_command(text: str) -> str | None:
    """Extract the window a spoken command names, or None. Pure.

    Returns the raw target words; matching them to a window is a separate step
    so the grammar can be tested without a desktop.
    """
    match = _FOCUS_RE.fullmatch((text or "").strip())
    if not match:
        return None
    target = match.group("target").strip()
    return target or None


# ── matching ─────────────────────────────────────────────────────────────────


def match_window(query: str, windows: list[WindowRef]) -> WindowRef | None:
    """Best window for *query*, or None when absent or ambiguous. Pure.

    Ambiguity is treated as failure rather than resolved by tie-break order:
    focusing the wrong window sends the user's next sentence somewhere they are
    not looking.
    """
    if not query or not windows:
        return None
    by_title: dict[str, list[WindowRef]] = {}
    for window in windows:
        by_title.setdefault(window.title, []).append(window)

    ranked = [(title, score) for title, score in fuzzy_rank(query, list(by_title))
              if score >= MATCH_THRESHOLD]
    if not ranked:
        return None
    if len(ranked) > 1 and (ranked[0][1] - ranked[1][1]) < AMBIGUITY_MARGIN:
        log.info("Window query %r is ambiguous between %r and %r; not focusing.",
                 query, ranked[0][0], ranked[1][0])
        return None
    winners = by_title[ranked[0][0]]
    if len(winners) > 1:
        log.info("Window query %r matches %d windows titled %r; not focusing.",
                 query, len(winners), ranked[0][0])
        return None
    return winners[0]


def focus_by_name(query: str, backend: WindowBackend | None) -> WindowRef | None:
    """Match and focus in one step. None when refused; nothing is focused then."""
    if backend is None:
        return None
    window = match_window(query, backend.list_windows())
    if window is None:
        return None
    return window if backend.focus(window.id) else None


# ── X11 backend ──────────────────────────────────────────────────────────────


class XdotoolWindows:
    """WindowBackend over the `xdotool` CLI (X11 only)."""

    def __init__(self, runner: Callable[[list[str]], str] | None = None) -> None:
        self._run = runner or self._default_runner

    @staticmethod
    def _default_runner(argv: list[str]) -> str:
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=2.0, check=True
        ).stdout

    def list_windows(self) -> list[WindowRef]:
        try:
            ids = self._run(
                ["xdotool", "search", "--onlyvisible", "--name", "."]
            ).split()
        except Exception:
            log.debug("xdotool search failed", exc_info=True)
            return []
        out: list[WindowRef] = []
        for wid in ids:
            try:
                title = self._run(["xdotool", "getwindowname", wid]).strip()
            except Exception:
                continue
            if title:
                out.append(WindowRef(id=wid, title=title))
        return out

    def focus(self, window_id: str) -> bool:
        try:
            self._run(["xdotool", "windowactivate", "--sync", window_id])
            return True
        except Exception:
            log.debug("xdotool windowactivate failed", exc_info=True)
            return False

    # ── layout / workspace actions ───────────────────────────────────────────
    #
    # Every probe below is a separate xdotool call that can fail on its own, and a
    # failure here must be reported rather than swallowed: the caller falls back to
    # typing the phrase as text, which is the right answer when the action did not
    # happen. Returning True on a no-op is how this feature was broken before.

    def _active_window(self) -> str | None:
        try:
            wid = self._run(["xdotool", "getactivewindow"]).strip()
        except Exception:
            log.debug("xdotool getactivewindow failed", exc_info=True)
            return None
        return wid or None

    def _screen(self) -> Screen | None:
        try:
            out = self._run(["xdotool", "getdisplaygeometry"]).split()
            return Screen(width=int(out[0]), height=int(out[1]))
        except Exception:
            log.debug("xdotool getdisplaygeometry failed", exc_info=True)
            return None

    def _current_desktop(self) -> int | None:
        try:
            return int(self._run(["xdotool", "get_desktop"]).strip())
        except Exception:
            # Not every window manager implements _NET_CURRENT_DESKTOP. That makes
            # "next workspace" unavailable, not broken -- absolute "workspace 3"
            # does not come through here and still works.
            log.debug("xdotool get_desktop failed", exc_info=True)
            return None

    def perform(self, action: WmAction) -> bool:
        """Run a WmAction against the active window. See WindowBackend.perform."""
        # `workspace` acts on the desktop, not on a window, so it must not require
        # one -- switching workspaces with no window focused is perfectly ordinary.
        needs_window = action.kind not in ("workspace", "workspace_rel")
        window = self._active_window() if needs_window else ""
        if needs_window and not window:
            return False
        try:
            steps = plan(
                action,
                window or "",
                screen=self._screen() if action.kind in ("snap", "center") else None,
                current_desktop=(
                    self._current_desktop() if action.kind == "workspace_rel" else None
                ),
            )
        except UnsupportedAction as exc:
            log.info("windowctl: cannot perform %s: %s", action, exc)
            return False
        for argv in steps:
            try:
                self._run(argv)
            except Exception:
                log.debug("windowctl step failed: %s", argv, exc_info=True)
                return False
        return True


def wayland_limitation() -> str:
    """Why voice window focus cannot work on Wayland. Used by `yazses doctor`."""
    return (
        "Wayland does not let one application focus another's window, and no "
        "portal exposes it — so voice window control is X11-only for now. "
        "Layout commands your compositor binds itself still work."
    )


def build_window_backend(session_type: str = "") -> WindowBackend | None:
    """An X11 window backend, or None with the reason logged.

    Deliberately returns None on Wayland instead of a backend that fails at every
    call: a feature that cannot work should be reported as unavailable, not as
    broken.
    """
    session = (session_type or "").lower()
    if "wayland" in session:
        log.info("Voice window focus: %s", wayland_limitation())
        return None
    if not shutil.which("xdotool"):
        log.info("Voice window focus: xdotool not installed; disabled.")
        return None
    return XdotoolWindows()
