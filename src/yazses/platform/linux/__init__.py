"""Linux backend bundle."""

from __future__ import annotations

import logging
import os
import weakref
from collections.abc import Callable, Mapping
from typing import Any

from yazses.platform.base import LINUX_PLATFORM_NAME, ClickObserverFactory, Platform
from yazses.platform.linux.paths import build_paths
from yazses.pointer.base import PointerSink, PointerUnsupportedError

log = logging.getLogger(__name__)

#: Why a native Wayland session has no click observer (#607), in the sentence the daemon
#: log, `yazses doctor` and `yazses gaze status` repeat. Not a missing package: Wayland
#: delivers button events only to the focused client, the compositor interfaces that could
#: report them are private, and the XDG RemoteDesktop portal is output-only -- it accepts
#: synthetic input, it never reports the user's. XInput2 on XWayland would "work" and see
#: only X clients' clicks, which is a plausible, partial sample stream the refiner must
#: never be fed.
WAYLAND_CLICK_REASON = (
    "a native Wayland session exposes no global click stream: button events reach only the "
    "focused client, the compositor APIs that could report them are private, and the XDG "
    "RemoteDesktop portal only sends input, it never reports it; log in to an X11 session "
    "to let implicit refinement learn from clicks"
)

#: No `DISPLAY`, no `WAYLAND_DISPLAY`: a service or SSH environment with nothing to click.
HEADLESS_CLICK_REASON = (
    "no desktop session was detected (neither DISPLAY nor WAYLAND_DISPLAY is set), so there "
    "are no clicks to observe"
)


def _make_hotkey(key_id: str, threshold_ms: int, on_start, on_end):
    in_snap = "SNAP" in os.environ
    has_x11 = bool(os.environ.get("DISPLAY"))

    if in_snap and has_x11:
        try:
            from yazses.platform.linux.hotkey_xgrab import X11GrabHotkey
            return X11GrabHotkey(
                key_id=key_id,
                threshold_ms=threshold_ms,
                on_hold_start=on_start,
                on_hold_end=on_end,
            )
        except Exception as exc:
            log.warning("X11GrabHotkey unavailable (%s), falling back to evdev", exc)

    from yazses.platform.linux.hotkey import LinuxHotkey
    return LinuxHotkey(
        key_id=key_id,
        threshold_ms=threshold_ms,
        on_hold_start=on_start,
        on_hold_end=on_end,
    )


def _make_tray():
    """Build the Linux tray backend (PySide6 QSystemTrayIcon)."""
    from yazses.platform.linux.tray import LinuxTray

    return LinuxTray()


def build_pointer_sink() -> PointerSink:
    """Open this Linux session's pointer output (ADR-v2-146), or say why there is none.

    Separate from :func:`build_platform` on purpose. `Platform` is built once at start-up
    for every user, and a pointer sink must be opened only when a pointer consumer is
    actually enabled — ADR-v2-146 rule 7, which matters most on Wayland where opening one
    means asking the user for consent. Folding it into the bundle would take a display
    connection for everybody who only ever dictates.

    X11 only, for now, and that is a narrower claim than "Linux": XTEST is an X-server
    extension, so this reaches a real X session, and on a Wayland session it reaches
    whatever XWayland exposes — which is not the native Wayland pointer. A session with no
    X server at all gets ``PointerUnsupportedError`` rather than something that accepts
    every request and moves nothing. The Wayland path is to extend the RemoteDesktop
    portal session in `src/yazses/inject/portal.py`, which is a separate backend; until it
    exists this function is the only pointer output Linux has, and the choice between them
    is not made here.
    """
    from yazses.platform.linux.pointer_x11 import build_x11_pointer_sink

    return build_x11_pointer_sink()


def _pointer_factory(injector: object | None = None) -> PointerSink:
    """The lazy ``Platform.pointer_factory`` for Linux: X11 where X11 is the real session.

    Refuses to open XTEST on a native Wayland session. XTEST reaches only XWayland, so a
    sink built on a Wayland desktop would accept every request and move a pointer no
    Wayland client can see -- the silent no-op ADR-v2-146 forbids. There the pointer is the
    RemoteDesktop portal's, and it must extend the session **dictation already uses**
    (rule 6), so it is asked of the live *injector* rather than built from the environment:
    a second portal client would be a second consent dialog and a second grant.

    *injector* is the daemon's own :class:`LinuxInjector`; ``None`` (no injector was ever
    built through this platform) is a Wayland refusal with its own reason. X11 never reads
    it, so that path is unchanged.
    """
    session = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if session == "wayland":
        open_sink = getattr(injector, "pointer_sink", None)
        if open_sink is None:
            raise PointerUnsupportedError(
                "native Wayland session: the X11 pointer backend only reaches XWayland, "
                "and there is no live injector whose portal session the pointer could extend"
            )
        sink: PointerSink = open_sink()
        return sink
    return build_pointer_sink()


def _click_observer_route(
    environ: Mapping[str, str] | None = None,
) -> tuple[ClickObserverFactory | None, str | None]:
    """``(factory, None)`` on X11; ``(None, reason)`` on Wayland or with no desktop (#607).

    Decided when the bundle is built, from the same session classifier gaze routing uses
    (:func:`yazses.gaze.target_semantics.classify_session`), so "no gaze target on Wayland"
    and "no click observer on Wayland" can never disagree about which session this is.
    The factory itself opens nothing -- `start` does, and only the refinement runtime calls
    that, only when ``[gaze_refine] enabled = true``.
    """
    from yazses.gaze.target_semantics import classify_session

    session = classify_session(os.environ if environ is None else environ)
    if session == "x11":
        return _make_click_observer, None
    if session.startswith("wayland"):
        return None, WAYLAND_CLICK_REASON
    return None, HEADLESS_CLICK_REASON


def _make_click_observer() -> Any:
    from yazses.platform.linux.click_observer_x11 import build_x11_click_observer

    return build_x11_click_observer()


class _InjectorRoute:
    """Ties ``injector_factory`` to ``pointer_factory`` without widening the Protocols.

    The Wayland pointer must extend the injector's portal session, but the platform bundle
    hands out two zero-argument factories and the pointer's is called by the Head-Pointer,
    which knows nothing of injectors. This remembers the injector the daemon built (weakly,
    so the bundle never keeps one alive) and lets the pointer factory ask it. The daemon
    builds exactly one; the CLI's one-shot commands build theirs and never ask for a
    pointer.
    """

    def __init__(self, make: Callable[[], Any]) -> None:
        self._make = make
        self._ref: weakref.ReferenceType[Any] | None = None

    def injector_factory(self) -> Any:
        injector = self._make()
        self._ref = weakref.ref(injector)
        return injector

    def pointer_factory(self) -> PointerSink:
        injector = self._ref() if self._ref is not None else None
        return _pointer_factory(injector)


def build_platform() -> Platform:
    from yazses.platform.linux.injector import LinuxInjector
    from yazses.platform.linux.ipc import UnixSocketIpcClient, UnixSocketIpcServer
    from yazses.platform.linux.lifecycle import LinuxLifecycle
    from yazses.platform.linux.permissions import LinuxPermissions

    paths = build_paths()
    route = _InjectorRoute(LinuxInjector)
    click_observer_factory, click_observer_reason = _click_observer_route()
    return Platform(
        name=LINUX_PLATFORM_NAME,
        default_hotkey="right_alt",
        paths=paths,
        permissions=LinuxPermissions(),
        lifecycle=LinuxLifecycle(paths=paths),
        hotkey_factory=_make_hotkey,
        injector_factory=route.injector_factory,
        ipc_server_factory=lambda socket_path: UnixSocketIpcServer(socket_path),
        ipc_client_factory=lambda socket_path: UnixSocketIpcClient(socket_path),
        tray_factory=_make_tray,
        tray_default_enabled=True,
        # A factory, so nothing is opened here (ADR-v2-146 rule 7): a pointer consumer
        # calls it, and dictation alone never takes a display connection.
        pointer_factory=route.pointer_factory,
        # X11 only (#607): XInput2 raw presses carry no window and take no grab. None on
        # Wayland, with the reason, rather than an observer that sees only XWayland clients.
        click_observer_factory=click_observer_factory,
        click_observer_unavailable_reason=click_observer_reason,
    )


__all__ = [
    "HEADLESS_CLICK_REASON",
    "WAYLAND_CLICK_REASON",
    "build_platform",
    "build_pointer_sink",
]
