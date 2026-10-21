"""Which desktop capabilities a gaze target needs, and which each session offers (#418).

Glance-Type asks "which window should receive the next dictation?". Answering it needs
three capabilities from the desktop, and a fourth that is often mistaken for them:

* ``ABSOLUTE_POSITION`` -- a gaze point is a pixel in coordinates the desktop shares with
  this process, so it can be compared with anything else on screen;
* ``WINDOW_GEOMETRY`` -- the rectangles of *other* applications' windows, to find the one
  under that pixel;
* ``WINDOW_FOCUS`` -- the right to raise and focus one of those windows, so the next
  keystrokes land in it;
* ``POINTER_INJECTION`` -- moving and clicking a cursor (#403, ADR-v2-146). It is an
  **output** capability and is deliberately *not* an input to the gaze-target decision:
  the RemoteDesktop portal moves a cursor in a stream's coordinate space and returns no
  pointer position, no window list, no geometry and no focus. Pointer permission does not
  make a gaze target, and :func:`gaze_target_supported` proves it by never reading it.

This module is the platform matrix, as data: for each ``eyeeval.schema.SESSION_TYPES``
bucket, what an ordinary client is given for each capability, through which interface, and
which cited source says so. The sources and the reasoning are in
``design/specs/eye-wayland-gaze-target.md``; every source id used below must appear there
(``tests/test_gaze_target_capabilities.py`` checks both directions).

**The derivation rule** (:func:`gaze_target_supported`): a session supports a gaze target
only when all three target capabilities are :attr:`Support.YES` -- available to an ordinary,
unprivileged client through a stable, documented interface. A capability that exists only
through one compositor's own interface (a desktop-shell-only protocol, an allow-listed
D-Bus API, a shell extension, compositor scripting) is :attr:`Support.COMPOSITOR_SPECIFIC`
and never counts: #418's third acceptance criterion is that no compositor-private path is a
default requirement. A future, opt-in, validated backend for one of those paths would be a
new ``TargetBasis`` in :mod:`yazses.gaze.target_semantics`, not a reinterpretation of this
rule.

Pure: constants and functions over them. Nothing here talks to a compositor.
"""
from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

__all__ = [
    "Capability",
    "CapabilityFact",
    "SESSION_CAPABILITIES",
    "SOURCES",
    "Support",
    "TARGET_CAPABILITIES",
    "capabilities_for",
    "gaze_target_supported",
    "summarize",
]


class Capability(str, enum.Enum):
    """One thing a desktop may let a client do. See the module docstring."""

    ABSOLUTE_POSITION = "absolute_position"
    WINDOW_GEOMETRY = "window_geometry"
    WINDOW_FOCUS = "window_focus"
    POINTER_INJECTION = "pointer_injection"


#: The three a gaze target is made of. ``POINTER_INJECTION`` is absent on purpose.
TARGET_CAPABILITIES: tuple[Capability, ...] = (
    Capability.ABSOLUTE_POSITION,
    Capability.WINDOW_GEOMETRY,
    Capability.WINDOW_FOCUS,
)


class Support(str, enum.Enum):
    """How an ordinary client gets a capability on a session."""

    #: Through a stable, documented, cross-desktop interface, with no extra grant.
    YES = "yes"
    #: Through an XDG desktop portal, after the user grants it -- and only where the
    #: desktop's portal backend implements that portal.
    CONSENT = "consent"
    #: Only through one compositor's own interface: a protocol reserved for the desktop
    #: shell, a D-Bus API behind an allow-list, a shell extension or compositor scripting.
    #: Real, but never a default requirement (#418), so it never makes a gaze target.
    COMPOSITOR_SPECIFIC = "compositor_specific"
    #: No interface gives it to an ordinary client.
    NO = "no"


#: Citation ids -> (title, landing page). Landing pages, never a file (AGENTS.md rule 10).
SOURCES: Mapping[str, tuple[str, str]] = {
    "wayland-core": (
        "Wayland core protocol (wl_pointer: surface-local coordinates)",
        "https://wayland.app/protocols/wayland",
    ),
    "portal-remotedesktop": (
        "XDG Desktop Portal: org.freedesktop.portal.RemoteDesktop",
        "https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html",
    ),
    "portal-screencast": (
        "XDG Desktop Portal: org.freedesktop.portal.ScreenCast",
        "https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html",
    ),
    "portal-inputcapture": (
        "XDG Desktop Portal: org.freedesktop.portal.InputCapture",
        "https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.InputCapture.html",
    ),
    "xdg-activation": (
        "xdg-activation-v1 (staging)",
        "https://wayland.app/protocols/xdg-activation-v1",
    ),
    "wlr-foreign-toplevel": (
        "wlr-foreign-toplevel-management-unstable-v1",
        "https://wayland.app/protocols/wlr-foreign-toplevel-management-unstable-v1",
    ),
    "ext-foreign-toplevel-list": (
        "ext-foreign-toplevel-list-v1 (staging)",
        "https://wayland.app/protocols/ext-foreign-toplevel-list-v1",
    ),
    "kde-plasma-window-management": (
        "KDE org_kde_plasma_window_management",
        "https://wayland.app/protocols/kde-plasma-window-management",
    ),
    "kwin-scripting": (
        "KWin Scripting API (KWin 6)",
        "https://develop.kde.org/docs/plasma/kwin/api/",
    ),
    "gnome-shell-introspect": (
        "GNOME Discourse: org.gnome.Shell.Introspect GetWindows is allow-listed (2024)",
        "https://discourse.gnome.org/t/unable-to-call-the-remote-getwindows-gnome-method-via-dbus/21201",
    ),
    "atspi-component": (
        "AT-SPI org.a11y.atspi.Component (coord_type, GrabFocus)",
        "https://ubuntu.com/desktop/docs/en/latest/reference/accessibility/dbus/org.a11y.atspi.Component",
    ),
    "gtk4-atspi-screen-coords": (
        "GTK 4 source, gtk/a11y/gtkatspiutils.c: a SCREEN coord_type answers (0, 0)",
        "https://gitlab.gnome.org/GNOME/gtk/-/blob/main/gtk/a11y/gtkatspiutils.c",
    ),
    "gtk4-atspi-grabfocus": (
        "GTK 4 source, gtk/a11y/gtkatspicomponent.c: GrabFocus returns NotSupported",
        "https://gitlab.gnome.org/GNOME/gtk/-/blob/main/gtk/a11y/gtkatspicomponent.c",
    ),
    "xdpw": (
        "xdg-desktop-portal-wlr (implements ScreenCast and Screenshot)",
        "https://github.com/emersion/xdg-desktop-portal-wlr",
    ),
    "ewmh": (
        "Extended Window Manager Hints (_NET_CLIENT_LIST, _NET_ACTIVE_WINDOW)",
        "https://specifications.freedesktop.org/wm-spec/latest/",
    ),
    "xtest": (
        "X11 XTEST extension",
        "https://www.x.org/releases/X11R7.7/doc/xextproto/xtest.html",
    ),
}


@dataclass(frozen=True)
class CapabilityFact:
    """What one session offers for one capability, and why we believe it."""

    capability: Capability
    support: Support
    #: The interface it comes through, or the one that would have to and does not.
    via: str
    #: Ids into :data:`SOURCES`.
    sources: tuple[str, ...] = ()


def _f(cap: Capability, support: Support, via: str, *sources: str) -> CapabilityFact:
    return CapabilityFact(cap, support, via, tuple(sources))


_C = Capability
_S = Support

#: ``SESSION_TYPES`` bucket -> the matrix row. ``windows``/``macos`` are absent: the OS
#: APIs there (UI Automation, the macOS Accessibility API) are outside #418, and YazSes has
#: no window backend on either yet; :func:`capabilities_for` returns ``()`` for them.
SESSION_CAPABILITIES: Mapping[str, tuple[CapabilityFact, ...]] = {
    "x11": (
        _f(_C.ABSOLUTE_POSITION, _S.YES, "X11 root-window coordinates", "ewmh"),
        _f(_C.WINDOW_GEOMETRY, _S.YES, "EWMH _NET_CLIENT_LIST + window geometry", "ewmh"),
        _f(_C.WINDOW_FOCUS, _S.YES, "EWMH _NET_ACTIVE_WINDOW (xdotool windowactivate)", "ewmh"),
        _f(_C.POINTER_INJECTION, _S.YES, "XTEST", "xtest"),
    ),
    "wayland_gnome": (
        _f(_C.ABSOLUTE_POSITION, _S.NO,
           "none: wl_pointer reports surface-local coordinates; portal coordinates are "
           "stream- or zone-relative", "wayland-core", "portal-screencast",
           "portal-inputcapture"),
        _f(_C.WINDOW_GEOMETRY, _S.COMPOSITOR_SPECIFIC,
           "org.gnome.Shell.Introspect (allow-listed to the portals or unsafe mode) or a "
           "Shell extension; AT-SPI screen coordinates are unsupported in GTK 4",
           "gnome-shell-introspect", "atspi-component", "gtk4-atspi-screen-coords"),
        _f(_C.WINDOW_FOCUS, _S.COMPOSITOR_SPECIFIC,
           "a Shell extension; xdg-activation only lets a client activate its own "
           "surface with a token; AT-SPI GrabFocus is unsupported in GTK 4",
           "xdg-activation", "atspi-component", "gtk4-atspi-grabfocus"),
        _f(_C.POINTER_INJECTION, _S.CONSENT, "RemoteDesktop portal (xdg-desktop-portal-gnome)",
           "portal-remotedesktop"),
    ),
    "wayland_kde": (
        _f(_C.ABSOLUTE_POSITION, _S.COMPOSITOR_SPECIFIC,
           "KWin scripting workspace.cursorPos; wl_pointer itself is surface-local",
           "kwin-scripting", "wayland-core"),
        _f(_C.WINDOW_GEOMETRY, _S.COMPOSITOR_SPECIFIC,
           "org_kde_plasma_window_management (reserved for the desktop shell) or KWin "
           "scripting frameGeometry", "kde-plasma-window-management", "kwin-scripting"),
        _f(_C.WINDOW_FOCUS, _S.COMPOSITOR_SPECIFIC,
           "KWin scripting workspace.activeWindow or plasma window management; "
           "xdg-activation only activates the caller's own surface",
           "kwin-scripting", "kde-plasma-window-management", "xdg-activation"),
        _f(_C.POINTER_INJECTION, _S.CONSENT, "RemoteDesktop portal (xdg-desktop-portal-kde)",
           "portal-remotedesktop"),
    ),
    "wayland_other": (
        _f(_C.ABSOLUTE_POSITION, _S.NO,
           "none: wl_pointer reports surface-local coordinates", "wayland-core"),
        _f(_C.WINDOW_GEOMETRY, _S.COMPOSITOR_SPECIFIC,
           "compositor IPC only (e.g. Sway, Hyprland); the foreign-toplevel protocols list "
           "windows but carry no geometry", "wlr-foreign-toplevel", "ext-foreign-toplevel-list"),
        _f(_C.WINDOW_FOCUS, _S.COMPOSITOR_SPECIFIC,
           "wlr-foreign-toplevel-management activate, on wlroots-family compositors only "
           "(not GNOME, not KDE)", "wlr-foreign-toplevel"),
        _f(_C.POINTER_INJECTION, _S.CONSENT,
           "RemoteDesktop portal, only where the portal backend implements it "
           "(xdg-desktop-portal-wlr does not)", "portal-remotedesktop", "xdpw"),
    ),
    "headless": tuple(
        _f(cap, _S.NO, "no desktop session") for cap in (*TARGET_CAPABILITIES, _C.POINTER_INJECTION)
    ),
}


def capabilities_for(session: str) -> tuple[CapabilityFact, ...]:
    """The matrix row for *session*, or ``()`` when it was not assessed. Pure."""
    return SESSION_CAPABILITIES.get((session or "").strip().lower(), ())


def gaze_target_supported(facts: Iterable[CapabilityFact]) -> bool:
    """Whether *facts* make a gaze target: all three target capabilities are ``YES``. Pure.

    ``POINTER_INJECTION`` is never read, and ``COMPOSITOR_SPECIFIC``/``CONSENT`` never
    count. An unassessed session (no facts) supports nothing.
    """
    by_cap = {f.capability: f.support for f in facts}
    return all(by_cap.get(cap) is Support.YES for cap in TARGET_CAPABILITIES)


_LABELS = {
    Capability.ABSOLUTE_POSITION: "screen position",
    Capability.WINDOW_GEOMETRY: "other windows' geometry",
    Capability.WINDOW_FOCUS: "focus another window",
    Capability.POINTER_INJECTION: "pointer injection",
}
_WORDS = {
    Support.YES: "yes",
    Support.CONSENT: "with permission",
    Support.COMPOSITOR_SPECIFIC: "compositor-specific only",
    Support.NO: "no",
}


def summarize(facts: Iterable[CapabilityFact]) -> str:
    """One line a status row can print: ``screen position: no; ...``. Pure.

    Pointer injection is printed last and labelled separate, so a reader cannot take a
    granted pointer permission for a gaze target.
    """
    items = list(facts)
    target = [f for f in items if f.capability is not Capability.POINTER_INJECTION]
    pointer = [f for f in items if f.capability is Capability.POINTER_INJECTION]
    parts = [f"{_LABELS[f.capability]}: {_WORDS[f.support]}" for f in target]
    parts += [
        f"{_LABELS[f.capability]} (separate, not a target): {_WORDS[f.support]}" for f in pointer
    ]
    return "; ".join(parts)
