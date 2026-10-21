"""What a gaze target IS on this session, said once and honestly (EYE-WAYLAND-001, #418).

Glance-Type's question is "which window should receive the next dictation?". Answering it
takes three things from the desktop, and they are separate capabilities:

* an **absolute screen position** -- the calibrated gaze point is a pixel in desktop
  coordinates, so it is only meaningful where the desktop uses those coordinates;
* the **geometry of other applications' windows** -- to find the one under that pixel;
* the right to **focus** one -- so the next keystrokes land there.

X11 answers all three (``xdotool``/``xrandr``). A Wayland client gets none of them: the
compositor owns the global pointer position and every window's geometry, an application
sees only its own surfaces, and no portal lets one client raise another's window
(``windowctl.focus.wayland_limitation`` states the same fact for voice focus). The
RemoteDesktop portal that gives YazSes *pointer injection* (#403, ADR-v2-146) is a different
boundary: it lets the user's consent move a cursor, and it reveals none of the three above.
Pointer permission therefore does **not** make a gaze target; this module is where that
sentence lives in code.

**The definition.** On a session without an absolute desktop position the gaze target is
*nothing*: the planner reports ``TargetBasis.NONE`` with the reason, look-to-pane abstains,
and dictation stays in the focused window (the pre-existing fall-back, which is also the
only thing a destructive deixis phrase may fall back to under
``[gaze] refuse_destructive_fallback``). It is deliberately not a coarse screen zone: a zone
is a position, and nothing on Wayland can turn a position into a window or an action, so a
zone would be a number with no consumer -- and a number a future caller could mistake for
one. Abstaining with a reason is the entire contract; if a supported accessibility-tree path
is ever validated on real GNOME and KDE sessions, it is a new ``TargetBasis`` here, not a
reinterpretation of this one.

**The capability model.** Each plan carries its session's row of the platform matrix in
:mod:`yazses.gaze.target_capabilities` -- screen position, other windows' geometry, focus,
and pointer injection kept apart -- and states what gaze may honestly do with it:
:attr:`GazeTargetPlan.dictation_route` (the gazed window, or the focused window only) and
:attr:`GazeTargetPlan.destructive_deixis` (decided by ``[gaze]`` config where gaze can name
a window, **refused** where it cannot, whatever ``refuse_destructive_fallback`` says: with
no gaze target, the focused window is not a stand-in for one). The matrix, its sources and
the GNOME/KDE findings are in ``design/specs/eye-wayland-gaze-target.md``.

Pure: it reads nothing. :func:`classify_session` takes the environment and the OS-fixed
bucket as arguments (the caller gets the latter from ``describe_host()``, the platform
seam), so every row of the matrix is reachable from any machine.
"""
from __future__ import annotations

import enum
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from yazses.gaze.target_capabilities import (
    CapabilityFact,
    capabilities_for,
    gaze_target_supported,
    summarize,
)

__all__ = [
    "DestructiveDeixis",
    "DictationRoute",
    "GazeTargetPlan",
    "TargetBasis",
    "WAYLAND_REASON",
    "classify_session",
    "describe_gaze_target",
    "plan_gaze_target",
]

#: ``XDG_SESSION_TYPE`` values that carry no evidence either way (a login shell, a service
#: manager that never imported the variable). With ``WAYLAND_DISPLAY`` set they mean Wayland.
_NO_SESSION_EVIDENCE = frozenset({"", "tty", "unspecified"})

#: ``(substring of XDG_CURRENT_DESKTOP, bucket)`` -- the same buckets as
#: ``eyeeval.schema.SESSION_TYPES``, so a status row and an evaluation result agree.
_WAYLAND_DESKTOPS = (("gnome", "wayland_gnome"), ("kde", "wayland_kde"), ("plasma", "wayland_kde"))

#: Why Wayland cannot name a gaze target. One sentence, no jargon a user must look up.
WAYLAND_REASON = (
    "Wayland gives an application no global pointer position, no geometry for other "
    "applications' windows and no way to focus them, so a gaze estimate cannot be turned "
    "into a window; look-to-pane abstains and dictation stays in the focused window"
)

_WAYLAND_REMEDY = (
    "log in to an X11 session (on GNOME, \"GNOME on Xorg\") to use look-to-pane; the "
    "Remote Desktop pointer permission is a separate capability and does not change this"
)


class TargetBasis(str, enum.Enum):
    """What a gaze estimate can be resolved against on this session."""

    #: Absolute desktop pixels plus the window rectangles to look them up in (X11).
    SCREEN_WINDOWS = "screen_windows"
    #: Nothing: the estimate cannot be resolved to a window; the caller abstains.
    NONE = "none"


class DictationRoute(str, enum.Enum):
    """Where the next dictation may go, given what gaze can know here."""

    #: The window under the calibrated gaze point (X11 look-to-pane).
    GAZED_WINDOW = "gazed_window"
    #: The window the user already focused. Gaze contributes nothing and claims nothing.
    FOCUSED_WINDOW = "focused_window"


class DestructiveDeixis(str, enum.Enum):
    """What a destructive gaze command ("close this") may do on this session."""

    #: Gaze can name a window; ``[gaze] confirm_destructive`` and
    #: ``refuse_destructive_fallback`` decide (ADR-v2-010, ADR-v2-148).
    BY_CONFIG = "by_config"
    #: Gaze can never name a window here, so the command is refused with feedback. The
    #: focused window is not a stand-in for a target that cannot exist (#418).
    REFUSE = "refuse"


@dataclass(frozen=True)
class GazeTargetPlan:
    """The answer to "what can a gaze target be here?" -- with the reason when it is nothing."""

    #: One of ``eyeeval.schema.SESSION_TYPES``.
    session: str
    basis: TargetBasis
    #: Always set, whether or not a target is possible.
    reason: str
    #: What would change the answer. Empty when nothing local can.
    remedy: str = ""
    #: This session's row of the platform matrix (`gaze/target_capabilities.py`); ``()``
    #: where it was not assessed (Windows, macOS).
    capabilities: tuple[CapabilityFact, ...] = ()

    @property
    def available(self) -> bool:
        return self.basis is not TargetBasis.NONE

    @property
    def dictation_route(self) -> DictationRoute:
        """Where the next dictation may go: the gazed window only when one can be named."""
        return DictationRoute.GAZED_WINDOW if self.available else DictationRoute.FOCUSED_WINDOW

    @property
    def destructive_deixis(self) -> DestructiveDeixis:
        """Whether "close this" is left to config or refused outright on this session."""
        return DestructiveDeixis.BY_CONFIG if self.available else DestructiveDeixis.REFUSE

    @property
    def capability_summary(self) -> str:
        """One printable line, pointer injection last and labelled separate. ``""`` if unassessed."""
        return summarize(self.capabilities)

    @property
    def absolute_position(self) -> bool:
        """Whether a gaze point is a pixel in coordinates the desktop shares with us."""
        return self.basis is TargetBasis.SCREEN_WINDOWS

    @property
    def window_geometry(self) -> bool:
        """Whether other applications' window rectangles can be read."""
        return self.basis is TargetBasis.SCREEN_WINDOWS

    @property
    def window_focus(self) -> bool:
        """Whether another application's window can be raised and focused."""
        return self.basis is TargetBasis.SCREEN_WINDOWS


def classify_session(
    environ: Mapping[str, str], *, fixed_session: str | None = None
) -> str:
    """The ``SESSION_TYPES`` bucket for *environ*. Pure.

    *fixed_session* is ``describe_host().fixed_session_type`` -- ``"windows"``/``"macos"``
    where the OS itself settles it, ``None`` on Linux and the BSDs.

    The one rule that differs from a plain ``XDG_SESSION_TYPE`` read: **a session variable
    that says nothing does not mean X11.** ``XDG_SESSION_TYPE`` is set by logind for the
    login session and is absent from a service or launcher environment that did not import
    it, while ``WAYLAND_DISPLAY`` is what the compositor exports. Reading only the first
    meant such a daemon fell through to ``xdotool`` -- which on a Wayland desktop *succeeds*,
    through XWayland, and sees only the X clients: a plausible window list that omits every
    native Wayland window, so a gaze point over a native window resolves to nothing or to a
    different, XWayland, one. An explicit ``x11`` still wins (a nested compositor exports
    ``WAYLAND_DISPLAY`` to its children inside an Xorg session).
    """
    if fixed_session:
        return fixed_session
    kind = (environ.get("XDG_SESSION_TYPE", "") or "").strip().lower()
    if kind == "x11":
        return "x11"
    wayland_display = bool((environ.get("WAYLAND_DISPLAY", "") or "").strip())
    if kind == "wayland" or (kind in _NO_SESSION_EVIDENCE and wayland_display):
        desktop = (environ.get("XDG_CURRENT_DESKTOP", "") or "").lower()
        for token, name in _WAYLAND_DESKTOPS:
            if token in desktop:
                return name
        return "wayland_other"
    if kind == "" and (environ.get("DISPLAY", "") or "").strip():
        return "x11"
    return "headless"


def plan_gaze_target(session: str, *, xdotool_available: bool | None = None) -> GazeTargetPlan:
    """What a gaze target can be on *session*. Pure.

    *xdotool_available* is ``None`` when it was not checked; only X11 reads it, and only a
    definite ``False`` refuses (an unchecked tool is not a missing one).

    The basis is derived from the session's capability row: a gaze target exists only where
    :func:`~yazses.gaze.target_capabilities.gaze_target_supported` says so (all three target
    capabilities available to an ordinary client) *and* YazSes has a backend for it, which
    today is X11 alone. A matrix row that ever became supportable elsewhere would still
    answer ``NONE`` here until a backend is written and validated.
    """
    kind = (session or "").strip().lower()
    facts = capabilities_for(kind)
    supported = gaze_target_supported(facts)
    if kind == "x11" and supported:
        if xdotool_available is False:
            return GazeTargetPlan(
                kind,
                TargetBasis.NONE,
                "X11 window routing needs `xdotool` and it is not installed",
                "run `yazses setup` (or install xdotool from your package manager)",
                facts,
            )
        return GazeTargetPlan(
            kind,
            TargetBasis.SCREEN_WINDOWS,
            "X11: gaze resolves to the window under a calibrated desktop pixel",
            "",
            facts,
        )
    if kind.startswith("wayland"):
        return GazeTargetPlan(kind, TargetBasis.NONE, WAYLAND_REASON, _WAYLAND_REMEDY, facts)
    if kind in ("windows", "macos"):
        return GazeTargetPlan(
            kind,
            TargetBasis.NONE,
            f"look-to-pane has no window backend on {kind} yet, so there is no gaze target "
            "to resolve and dictation stays in the focused window",
            "",
            facts,
        )
    return GazeTargetPlan(
        kind or "headless",
        TargetBasis.NONE,
        "no desktop session was detected (headless), so there is no screen to look at",
        "run YazSes from inside a graphical X11 session",
        capabilities_for("headless"),
    )


def describe_gaze_target(
    environ: Mapping[str, str] | None = None,
    *,
    fixed_session: Callable[[], str | None] | None = None,
    xdotool_available: Callable[[], bool] | None = None,
) -> GazeTargetPlan:
    """:func:`plan_gaze_target` for the machine this process runs on.

    Every probe is injectable. The OS-fixed bucket comes from ``describe_host()`` (the
    platform seam -- this module reads no ``sys.platform``); an unreadable host is "not
    fixed", never a failure, because a status command that raises removes the one place the
    answer is printed. ``xdotool`` is only looked for on an X11 session.
    """
    env = os.environ if environ is None else environ

    def _fixed() -> str | None:
        from yazses.platform.factory import describe_host

        return describe_host().fixed_session_type

    try:
        fixed = (fixed_session or _fixed)()
    except Exception:  # noqa: BLE001 - see docstring
        fixed = None
    session = classify_session(env, fixed_session=fixed)
    tool: bool | None = None
    if session == "x11":
        if xdotool_available is None:
            import shutil

            tool = shutil.which("xdotool") is not None
        else:
            tool = xdotool_available()
    return plan_gaze_target(session, xdotool_available=tool)
