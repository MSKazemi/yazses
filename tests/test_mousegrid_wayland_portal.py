"""The voice mouse grid on a Wayland portal session asks for no pointer and says why.

The grid places the pointer, and the RemoteDesktop portal pointer only moves it relatively,
so no portal grant can make the grid work. The grid used to ask the live session for a sink
when first opened: on a session already running for dictation that was refused with advice to
restart, which could not help, and the status showed only the exception's type.
"""
from __future__ import annotations

import pytest

from tests.test_pointer_portal import _FakePortalSession
from yazses.config import MousegridConfig
from yazses.inject import portal
from yazses.mousegrid.runtime import build_mousegrid
from yazses.platform import linux
from yazses.platform.linux.injector import LinuxInjector
from yazses.pointer.consent import PointerConsent, classify_portal_session

SCREEN = (0.0, 0.0, 900.0, 900.0)


@pytest.fixture(autouse=True)
def sandboxed_token(tmp_path, monkeypatch):
    monkeypatch.setenv("YAZSES_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("value", ["wayland", " Wayland "])
def test_a_wayland_session_declares_it_has_no_absolute_pointer(value: str) -> None:
    reason = linux._absolute_pointer_route({"XDG_SESSION_TYPE": value})
    assert reason == linux.WAYLAND_ABSOLUTE_POINTER_REASON


@pytest.mark.parametrize("environ", [{}, {"XDG_SESSION_TYPE": "x11"}, {"XDG_SESSION_TYPE": "tty"}])
def test_other_sessions_leave_the_answer_to_the_sink(environ: dict) -> None:
    assert linux._absolute_pointer_route(environ) is None


def test_the_declared_reason_matches_what_the_portal_backend_can_do() -> None:
    """If the portal ever gains absolute motion, the platform's refusal has to go."""
    assert portal.PORTAL_POINTER_CAPABILITIES.absolute_motion is False


@pytest.mark.parametrize("warmed", [False, True])
def test_the_grid_leaves_the_portal_session_alone(monkeypatch, warmed: bool) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    session = _FakePortalSession()
    injector = LinuxInjector.__new__(LinuxInjector)
    injector._primary = portal.PortalInjector(session=session)
    injector._fallback = None
    if warmed:
        session.ensure_started(1.0)
    rt = build_mousegrid(
        MousegridConfig(enabled=True),
        pointer_factory=lambda: linux._pointer_factory(injector),
        unavailable_reason=linux._absolute_pointer_route() or "",
    )
    rt._region_provider = lambda: SCREEN

    assert rt.handle_transcript("mouse grid") == "refused"
    reason = str(rt.status()["reason"])
    assert "absolute motion" in reason and "restart" not in reason
    assert session.wants_pointer is False
    if not warmed:
        session.ensure_started(1.0)
    assert session.select_options()["types"] == ("u", portal.DEVICE_KEYBOARD)


# --------------------------------------------------------------------------- #
# A keyboard-only session does not prove the compositor has no pointer
# --------------------------------------------------------------------------- #
def test_a_keyboard_only_report_does_not_blame_the_compositor_alone() -> None:
    report = classify_portal_session(
        closed=False, started=True, pointer_granted=False, last_error=""
    )
    assert report.state is PointerConsent.UNAVAILABLE
    assert "offers no portal pointer" not in report.detail
    assert "may offer none" in report.detail and "cancelled dialog" in report.detail


# --------------------------------------------------------------------------- #
# The start-up notice
# --------------------------------------------------------------------------- #
def test_with_a_saved_token_the_notice_does_not_promise_the_clipboard() -> None:
    title, body = portal.warmup_failure_notice(has_saved_token=True)
    assert "cancelled" in body and "saved approval" in body
    assert "clipboard" not in body and "pointer" not in body
    assert "Remote Desktop" in title


def test_with_a_saved_token_and_a_pointer_consumer_the_pointer_is_named() -> None:
    _, body = portal.warmup_failure_notice(has_saved_token=True, wants_pointer=True)
    assert "pointer may stay off" in body and "yazses restart" in body


@pytest.mark.parametrize("wants_pointer", [False, True])
def test_without_a_token_the_notice_names_the_clipboard_and_the_restart(
    wants_pointer: bool,
) -> None:
    _, body = portal.warmup_failure_notice(
        has_saved_token=False, wants_pointer=wants_pointer
    )
    assert "cancelled" in body and "clipboard" in body and "yazses restart" in body
    assert "saved approval" not in body


@pytest.mark.parametrize("token", ["", "saved-token"])
def test_the_daemon_sends_the_notice_that_matches_the_saved_token(
    monkeypatch, token: str
) -> None:
    import types

    from yazses.core.daemon import Daemon
    from yazses.system import notify as notify_mod

    class _RunNow:
        def __init__(self, target=None, **_kw):
            self._target = target

        def start(self):
            self._target()

    if token:
        portal.write_token(token)
    toasts: list[tuple] = []
    monkeypatch.setattr("yazses.core.daemon.threading.Thread", _RunNow)
    monkeypatch.setattr(notify_mod, "notify", lambda *a, **kw: toasts.append(a))
    backend = types.SimpleNamespace(warm=lambda: False, wants_pointer=False)

    Daemon._warm_portal_session(types.SimpleNamespace(_injector=backend))

    assert toasts[-1] == portal.warmup_failure_notice(has_saved_token=bool(token))
