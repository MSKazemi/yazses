"""Which pointer backend would drive the pointer here -- a pure prediction, held to the factory.

`plan_pointer_route` is what `yazses doctor` shows in its "Pointer output" row, so it must
agree with the thing the daemon actually runs: `platform/linux/__init__._pointer_factory`.
The first half is a table over the pure function. The second half is the parity test -- the
same session facts fed to the real factory -- because a doctor that names a different
backend from the one the daemon picks is worse than no doctor.

Nothing here opens a display, a portal session or a pointer: the factory is called with an
injector double and the X11 builder is replaced.
"""
from __future__ import annotations

import pytest

from yazses.platform import linux as linux_platform
from yazses.pointer.base import PointerUnsupportedError
from yazses.pointer.route import plan_pointer_route


@pytest.mark.parametrize(
    ("kwargs", "backend", "consent"),
    [
        ({"session_type": "x11", "xlib_available": True}, "x11", False),
        ({"session_type": "windows"}, "sendinput", False),
        ({"session_type": "macos"}, "quartz", False),
        ({"session_type": "wayland", "typing_backend": "portal"}, "portal", True),
        ({"session_type": "wayland_gnome", "typing_backend": "portal"}, "portal", True),
        ({"session_type": "wayland_kde", "typing_backend": "portal"}, "portal", True),
    ],
)
def test_the_backend_that_would_drive_the_pointer(kwargs, backend, consent) -> None:
    route = plan_pointer_route(**kwargs)
    assert route.backend == backend
    assert route.needs_consent is consent
    assert route.certain is True
    assert route.reason


@pytest.mark.parametrize("typing", ["ydotool", "wtype", "clipboard", "xdotool", "unicode"])
def test_wayland_without_portal_typing_has_no_pointer_and_says_how_to_get_one(typing) -> None:
    route = plan_pointer_route(session_type="wayland_gnome", typing_backend=typing)
    assert route.backend == ""
    assert typing in route.reason
    assert "XWayland" in route.reason, "the reason must say why XTEST is not the fallback"
    assert 'backend = "portal"' in route.remedy


def test_wayland_with_an_unknown_typing_backend_is_a_conditional_prediction() -> None:
    route = plan_pointer_route(session_type="wayland_gnome", typing_backend=None)
    assert route.backend == "portal"
    assert route.certain is False
    assert route.needs_consent is True


def test_x11_without_python_xlib_is_none_not_x11() -> None:
    route = plan_pointer_route(session_type="x11", xlib_available=False)
    assert route.backend == ""
    assert "python-xlib" in route.reason


def test_x11_with_an_unchecked_xlib_is_still_x11() -> None:
    assert plan_pointer_route(session_type="x11", xlib_available=None).backend == "x11"


def test_x11_without_a_display_is_none() -> None:
    route = plan_pointer_route(session_type="x11", xlib_available=True, display_present=False)
    assert route.backend == ""
    assert "DISPLAY" in route.reason


@pytest.mark.parametrize("session", ["headless", "", "tty", "weird"])
def test_no_desktop_no_pointer(session) -> None:
    route = plan_pointer_route(session_type=session)
    assert route.backend == ""
    assert "headless" in route.reason or "no desktop" in route.reason


@pytest.mark.parametrize("name", ["uinput", "xdotool", "ydotool"])
def test_typing_tools_are_never_named_as_pointer_backends(name) -> None:
    """They type; they are not pointer backends in this build, and saying so would be a claim."""
    for kind in ("x11", "wayland_gnome", "headless"):
        route = plan_pointer_route(session_type=kind, typing_backend=name, xlib_available=True)
        assert route.backend not in {"uinput", "xdotool", "ydotool"}


# ------------------------------------------------------------------- parity with the factory


class _InjectorWithPortal:
    """What `LinuxInjector` is when dictation types through the portal."""

    def pointer_sink(self):
        return object()


class _InjectorWithoutPortal:
    """What `LinuxInjector` is when dictation types some other way (it raises)."""

    def pointer_sink(self):
        raise PointerUnsupportedError("the Wayland pointer needs the Remote Desktop portal")


def test_on_wayland_the_factory_and_the_prediction_agree_for_portal_typing(monkeypatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert linux_platform._pointer_factory(_InjectorWithPortal()) is not None
    assert plan_pointer_route(session_type="wayland", typing_backend="portal").backend == "portal"


def test_on_wayland_the_factory_and_the_prediction_agree_for_other_typing(monkeypatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    with pytest.raises(PointerUnsupportedError):
        linux_platform._pointer_factory(_InjectorWithoutPortal())
    assert plan_pointer_route(session_type="wayland", typing_backend="ydotool").backend == ""


def test_on_wayland_with_no_injector_the_factory_refuses_xtest(monkeypatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    called = []
    monkeypatch.setattr(linux_platform, "build_pointer_sink", lambda: called.append(1))
    with pytest.raises(PointerUnsupportedError):
        linux_platform._pointer_factory(None)
    assert called == [], "XTEST must never be the Wayland fallback"


def test_off_wayland_the_factory_takes_the_x11_path_the_prediction_names(monkeypatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    sentinel = object()
    monkeypatch.setattr(linux_platform, "build_pointer_sink", lambda: sentinel)
    assert linux_platform._pointer_factory(None) is sentinel
    assert plan_pointer_route(session_type="x11", xlib_available=True).backend == "x11"
