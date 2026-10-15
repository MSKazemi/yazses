"""Which pointer backend would drive the pointer on this session -- a pure prediction.

``yazses doctor`` used to print ``Pointer output: unknown`` for ever, because the one
question it could ask (``platform.pointer_capabilities``) was never implemented. The facts
needed to answer are all cheap and read-only: the desktop session, which backend dictation
types through (the Wayland pointer rides *that* session, ADR-v2-146 rule 6), and whether
``python-xlib`` is importable. This module turns those into an answer. It opens nothing,
runs nothing and moves nothing -- :func:`plan_pointer_route` is a function of its arguments.

The rules mirror the factory in ``platform/linux/__init__.py`` and are held equal to it by
``tests/test_pointer_route.py``:

* **X11** -- XTEST through ``python-xlib`` (``x11``). No permission step.
* **Wayland** -- the RemoteDesktop portal (``portal``), and *only* when dictation itself
  types through the portal. XTEST on a Wayland session reaches XWayland, not the desktop,
  so it is deliberately not offered as a fallback: a pointer that accepts every request and
  moves nothing is what ADR-v2-146 forbids. The portal asks the user once per session.
* **Windows / macOS** -- ``sendinput`` / ``quartz``. No permission step YazSes can read.
* **Anything else** -- no backend, and the reason says which fact was missing.

``uinput`` and ``xdotool`` are *not* pointer backends in this build: ``xdotool`` types and
focuses windows, and ``uinput`` is only reachable through ``ydotool`` for typing. Naming
them here would claim a pointer path that does not exist.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PointerRoute", "plan_pointer_route"]


@dataclass(frozen=True)
class PointerRoute:
    """The backend that would drive the pointer, or why none would."""

    #: ``"portal"``, ``"x11"``, ``"sendinput"``, ``"quartz"`` -- or ``""`` for none.
    backend: str
    #: One sentence of why. Always set, whether or not a backend was found.
    reason: str
    #: What would change the answer. Empty when nothing local can.
    remedy: str = ""
    #: True when the backend asks the user's permission (so a consent state exists).
    needs_consent: bool = False
    #: False when the answer depends on something this prediction cannot see (the live
    #: selection of ``[injection] backend = "auto"``). Never rendered as certain.
    certain: bool = True


def plan_pointer_route(
    *,
    session_type: str,
    typing_backend: str | None = None,
    xlib_available: bool | None = None,
    display_present: bool = True,
) -> PointerRoute:
    """Predict the pointer backend. Pure.

    *session_type* is one of ``eyeeval.schema.SESSION_TYPES`` (``x11``, ``wayland_gnome``,
    ``wayland_kde``, ``wayland_other``, ``windows``, ``macos``, ``headless``). *typing_backend*
    is the name of the injection backend dictation would use (``portal``, ``ydotool``, ...)
    or ``None`` when that could not be determined. *xlib_available* is ``None`` when it was
    not checked. *display_present* is whether ``DISPLAY`` is set (X11 only).
    """
    kind = (session_type or "").strip().lower()
    if kind == "windows":
        return PointerRoute("sendinput", "Windows SendInput")
    if kind == "macos":
        return PointerRoute("quartz", "macOS Quartz events")
    if kind == "x11":
        if not display_present:
            return PointerRoute(
                "", "an X11 session was reported but DISPLAY is not set",
                "run YazSes from inside the graphical session",
            )
        if xlib_available is False:
            return PointerRoute(
                "", "X11 needs python-xlib for XTEST and it is not installed",
                "reinstall YazSes (python-xlib is a base dependency on Linux)",
            )
        return PointerRoute("x11", "X11 XTEST extension")
    if kind.startswith("wayland"):
        if typing_backend == "portal":
            return PointerRoute(
                "portal",
                "Wayland: the RemoteDesktop portal session dictation already uses",
                needs_consent=True,
            )
        if typing_backend is None:
            return PointerRoute(
                "portal",
                "Wayland: the RemoteDesktop portal, if dictation types through it; which "
                "typing backend is in use could not be determined",
                "run `yazses doctor` with the daemon up, or set `[injection] backend = "
                '"portal"`',
                needs_consent=True,
                certain=False,
            )
        return PointerRoute(
            "",
            f"Wayland: the pointer needs the Remote Desktop portal, but dictation types "
            f"through {typing_backend}, and XTEST would reach only XWayland",
            'set `[injection] backend = "portal"`, then `yazses restart`',
        )
    return PointerRoute(
        "",
        "no desktop session was detected (headless), so there is no pointer to drive",
        "run YazSes from inside a graphical session",
    )
