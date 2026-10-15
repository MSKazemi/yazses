"""An unanswered Remote Desktop dialog reads as *pending*, not as a keyboard-only refusal.

The real portal answers `CreateSession` at once and holds `Start` open until the user
answers the dialog. `_PortalSession._session_handle` is set by the first call, so a
classifier that read "has a handle" as "negotiated" reported an unanswered dialog as
"the desktop answered but granted no pointer device (keyboard only)". The fakes in
`test_pointer_portal.py` answer every call immediately, so none of them could see it; it
was found by running the daemon on a real GNOME Wayland session (2026-10-15).

This test gives the fake a `Start` that blocks until the test lets it return, which is the
shape of the real dialog, and reads the consent state from the Head-Pointer's own seam
while it is blocked.
"""

from __future__ import annotations

import threading

from tests.test_pointer_portal import KEYBOARD_AND_POINTER, _FakePortalSession
from yazses.inject import portal
from yazses.pointer.consent import PointerConsent


class _DialogOpenSession(_FakePortalSession):
    """`Start` does not return until ``answer`` is set -- an open consent dialog."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.answer = threading.Event()
        self.in_start = threading.Event()

    def _call_with_response(self, member, signature, body, timeout):
        if member == "Start":
            self.in_start.set()
            assert self.answer.wait(10.0), "the test never answered the fake dialog"
        return super()._call_with_response(member, signature, body, timeout)


def _negotiate_in_background(session: portal._PortalSession) -> threading.Thread:
    def _run() -> None:
        try:
            session.ensure_started()
        except portal.PortalUnavailable:
            pass  # a refused dialog is a case under test, read back through the session

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


def test_an_open_dialog_is_pending_not_keyboard_only() -> None:
    session = _DialogOpenSession(granted=KEYBOARD_AND_POINTER)
    sink = portal.DeferredPortalPointerSink(session)
    thread = _negotiate_in_background(session)
    try:
        assert session.in_start.wait(5.0), "the negotiation never reached Start"
        # CreateSession has returned, so the handle exists -- but nobody has answered.
        assert session._session_handle
        assert session.started is False
        report = sink.pointer_consent()
        assert report.state is PointerConsent.PENDING, report
        assert "keyboard only" not in report.detail
    finally:
        session.answer.set()
        thread.join(5.0)
    assert session.started is True
    assert sink.pointer_consent().state is PointerConsent.GRANTED


def test_the_answer_decides_granted_or_keyboard_only() -> None:
    # A keyboard-only answer is still reported -- but only AFTER the user has answered.
    session = _DialogOpenSession(granted=portal.DEVICE_KEYBOARD)
    sink = portal.DeferredPortalPointerSink(session)
    thread = _negotiate_in_background(session)
    try:
        assert session.in_start.wait(5.0)
        assert sink.pointer_consent().state is PointerConsent.PENDING
    finally:
        session.answer.set()
        thread.join(5.0)
    assert sink.pointer_consent().state is PointerConsent.UNAVAILABLE


def test_a_cancelled_dialog_is_denied_and_a_closed_session_is_not_started() -> None:
    session = _DialogOpenSession(refuse="Start")
    sink = portal.DeferredPortalPointerSink(session)
    thread = _negotiate_in_background(session)
    try:
        assert session.in_start.wait(5.0)
        assert sink.pointer_consent().state is PointerConsent.PENDING
    finally:
        session.answer.set()
        thread.join(5.0)
    assert session.started is False
    assert sink.pointer_consent().state is PointerConsent.DENIED

    ok = _DialogOpenSession(granted=KEYBOARD_AND_POINTER)
    ok.answer.set()
    ok.ensure_started()
    assert ok.started is True
    ok.close()
    assert ok.started is False
