"""Callers that arrive WHILE the Remote Desktop dialog is open (#403, EYE-PTR-004 audit).

`test_portal_consent_in_flight.py` fixed what the *Head-Pointer* reads while the dialog is
open. This file is its other half: what every *other* thread that touches the session does
in that window. The real portal answers `CreateSession` at once, so `_session_handle` is
set long before the user has answered anything; code that read the handle as "the session
is usable" let a dictation burst, or a pointer's first event, go out on a session the
compositor had not authorised. Nothing raised and nothing was typed -- the failure shape
that hid a dead Wayland injection path here for a year.

Every fake here BLOCKS where the real portal blocks (`_DialogOpenSession`, below), because
a fake that answers every call at once is exactly the double that could not see this.
Each helper thread is joined with a timeout, so a regression is a red test and not a hang.
"""

from __future__ import annotations

import threading
import time

import pytest

from tests.test_pointer_portal import KEYBOARD_AND_POINTER, _FakePortalSession
from yazses.inject import portal
from yazses.pointer.base import PointerBackendError
from yazses.pointer.consent import PointerConsent

JOIN_S = 5.0


class _DialogOpenSession(_FakePortalSession):
    """A named portal method blocks until ``answer`` is set -- an unanswered dialog.

    ``block_at="Start"`` is the real shape (the dialog is raised by `Start`);
    ``"CreateSession"`` models the earlier window in which no `SelectDevices` has been
    sent yet, so the device mask is still open to a late consumer.
    """

    def __init__(self, *, block_at: str = "Start", **kwargs) -> None:
        super().__init__(**kwargs)
        self.block_at = block_at
        self.answer = threading.Event()
        self.blocked = threading.Event()

    def _call_with_response(self, member, signature, body, timeout):
        if member == self.block_at:
            self.blocked.set()
            assert self.answer.wait(10.0), "the test never answered the fake dialog"
        return super()._call_with_response(member, signature, body, timeout)


def _in_background(fn) -> tuple[threading.Thread, list]:
    """Run *fn* on a thread; collect its exception (or None) so the test can read it."""
    outcome: list = []

    def _run() -> None:
        try:
            fn()
            outcome.append(None)
        except Exception as exc:  # noqa: BLE001 - the outcome is the thing under test
            outcome.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread, outcome


def _open_dialog(session: _DialogOpenSession) -> threading.Thread:
    """Start the negotiation `warm()` would, and return once the dialog is 'open'."""
    thread, _ = _in_background(lambda: session.ensure_started(portal.START_TIMEOUT_S))
    assert session.blocked.wait(JOIN_S), "the negotiation never reached the dialog"
    return thread


def _answer(session: _DialogOpenSession, thread: threading.Thread) -> None:
    session.answer.set()
    thread.join(JOIN_S)
    assert not thread.is_alive()


@pytest.fixture(autouse=True)
def sandboxed_token(tmp_path, monkeypatch):
    """No test here reads or writes the developer's own restore token.

    Importing `_FakePortalSession` does NOT import `test_pointer_portal`'s autouse
    sandbox, and the fake really calls `write_token`: the first draft of this file
    overwrote the host's restore token. Re-declared here on purpose.
    """
    monkeypatch.setenv("YAZSES_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def short_hot_path(monkeypatch):
    """The 5 s dictation budget, shortened so a refusal does not cost five seconds."""
    monkeypatch.setattr(portal, "HOT_PATH_TIMEOUT_S", 0.2)


# --------------------------------------------------------------------------- #
# Dictation arriving while the dialog is open
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "act",
    [
        lambda inj: inj.inject("hi"),
        lambda inj: inj.inject_backspaces(2),
        lambda inj: inj.inject_key_sequence(["ctrl+a"]),
    ],
    ids=["text", "backspaces", "key-sequence"],
)
def test_dictation_during_an_open_dialog_fails_fast_and_sends_no_key(
    short_hot_path, act
) -> None:
    session = _DialogOpenSession()
    injector = portal.PortalInjector(session=session)
    thread = _open_dialog(session)
    try:
        assert session._session_handle, "CreateSession has answered, as on the real portal"
        assert session.started is False

        began = time.monotonic()
        with pytest.raises(portal.PortalUnavailable, match="still waiting"):
            act(injector)

        assert time.monotonic() - began < 2.0, "it must not queue behind the dialog"
        assert session.notified == [], "no input may reach a session nobody authorised"
        assert session._last_used is None, "a refused burst is not 'use' for the reaper"
    finally:
        _answer(session, thread)
    assert session.started is True


def test_dictation_that_arrives_just_before_the_answer_waits_then_types() -> None:
    """The budget is a wait, not a refusal: an answer inside it is a normal start.

    And the order is the contract -- the first key leaves only after `Start` returned.
    """
    session = _DialogOpenSession()
    injector = portal.PortalInjector(session=session)
    thread = _open_dialog(session)

    typed, outcome = _in_background(lambda: injector.inject("a"))
    time.sleep(0.1)
    assert session.notified == [], "typed while the dialog was still open"
    _answer(session, thread)
    typed.join(JOIN_S)

    assert outcome == [None], outcome
    assert session.members == ["CreateSession", "SelectDevices", "Start"]
    assert [m for m, _, _ in session.notified] == ["NotifyKeyboardKeysym"] * 2


def test_a_cancelled_dialog_leaves_a_waiting_dictation_with_no_input_sent(
    short_hot_path,
) -> None:
    """Cancel while a dictation is waiting: it gets the clipboard, nothing else."""
    session = _DialogOpenSession(refuse="Start")
    injector = portal.PortalInjector(session=session)
    thread = _open_dialog(session)

    typed, outcome = _in_background(lambda: injector.inject("a"))
    _answer(session, thread)  # the user presses Cancel
    typed.join(JOIN_S)

    assert isinstance(outcome[0], portal.PortalUnavailable), outcome
    assert session.notified == []
    assert session.started is False


# --------------------------------------------------------------------------- #
# The pointer arriving while the dialog is open
# --------------------------------------------------------------------------- #
def test_a_deferred_pointer_sends_nothing_while_the_dialog_is_open() -> None:
    session = _DialogOpenSession()
    sink = portal.DeferredPortalPointerSink(session)
    thread = _open_dialog(session)
    try:
        for act in (
            lambda: sink.move_relative(1.0, 1.0),
            lambda: sink.click(),
            lambda: sink.scroll(0.0, 1.0),
        ):
            with pytest.raises(PointerBackendError, match="waiting"):
                act()
        assert session.notified == []
    finally:
        _answer(session, thread)
    sink.move_relative(1.0, 1.0)
    assert len(session.notified) == 1


def test_a_blocking_pointer_open_during_an_open_dialog_times_out_and_sends_nothing() -> None:
    """`open_pointer_sink` may wait for a human, but only within its own budget."""
    session = _DialogOpenSession()
    portal.DeferredPortalPointerSink(session)  # the consumer that put POINTER in the mask
    thread = _open_dialog(session)
    try:
        began = time.monotonic()
        with pytest.raises(PointerBackendError):
            portal.open_pointer_sink(session, start_timeout=0.2)
        assert time.monotonic() - began < 2.0
        assert session.notified == []
        assert session._pointer_consumers == 1, "the failed open must hand its count back"
    finally:
        _answer(session, thread)


def test_registering_a_pointer_consumer_never_waits_for_the_dialog() -> None:
    """The daemon starts the warm-up thread, then builds the Head-Pointer.

    If the warm-up thread wins the race it holds the session lock for the whole dialog,
    and a registration that takes that lock freezes the daemon's start-up -- hotkey
    included -- until a human answers. It must be answered at once, and truthfully: the
    mask is already out without POINTER, so the answer is "keyboard only".
    """
    session = _DialogOpenSession()
    thread = _open_dialog(session)  # SelectDevices went out keyboard-only
    try:
        registered, outcome = _in_background(lambda: portal.DeferredPortalPointerSink(session))
        registered.join(2.0)
        assert not registered.is_alive(), "the pointer registration blocked behind the dialog"
        assert isinstance(outcome[0], PointerBackendError), outcome
        assert "keyboard" in str(outcome[0])
        assert session._pointer_consumers == 0
    finally:
        _answer(session, thread)
    assert session.pointer_granted is False


def test_a_consumer_registered_before_the_mask_is_sent_still_rides_the_one_dialog() -> None:
    """The window between `CreateSession` and `SelectDevices` is still open to a consumer."""
    session = _DialogOpenSession(block_at="CreateSession")
    thread = _open_dialog(session)
    registered, outcome = _in_background(lambda: portal.DeferredPortalPointerSink(session))
    registered.join(2.0)
    assert not registered.is_alive(), "the pointer registration blocked behind the negotiation"
    assert outcome == [None], outcome
    _answer(session, thread)

    assert session.select_options()["types"] == ("u", KEYBOARD_AND_POINTER)
    assert session.pointer_granted is True
    assert session.members.count("Start") == 1


def test_the_idle_reaper_never_waits_for_the_dialog() -> None:
    """The reaper is a daemon thread; blocked on the lock it would pile up behind a dialog."""
    session = _DialogOpenSession()
    thread = _open_dialog(session)
    try:
        result: list[bool] = []
        reaped, outcome = _in_background(
            lambda: result.append(session.release_if_idle(60.0))
        )
        reaped.join(2.0)
        assert not reaped.is_alive(), "the reaper blocked behind the dialog"
        assert outcome == [None] and result == [False]
    finally:
        _answer(session, thread)
    assert session.started is True


# --------------------------------------------------------------------------- #
# Cancel, reconnect, restore token -- the state after the dialog
# --------------------------------------------------------------------------- #
def test_cancel_resets_everything_and_the_next_attempt_still_asks_for_the_pointer() -> None:
    session = _DialogOpenSession(refuse="Start")
    sink = portal.DeferredPortalPointerSink(session)
    conn_before = {}

    thread = _open_dialog(session)
    conn_before["conn"] = session._conn
    _answer(session, thread)  # Cancel

    assert session.started is False
    assert session._session_handle == ""
    assert session._conn is None
    assert conn_before["conn"].closed == 1, "the half-open connection must be closed"
    assert session.pointer_granted is False
    assert session.last_error
    assert sink.pointer_consent().state is PointerConsent.DENIED
    assert session.wants_pointer, "Cancel must not unregister the consumer"

    # The user asks again (restart / retry): the very same consumer rides the new mask.
    session.refuse = ""
    session.answer.set()
    session.calls.clear()
    session.ensure_started(1.0)
    assert session.select_options()["types"] == ("u", KEYBOARD_AND_POINTER)
    sink.move_relative(1.0, 0.0)
    assert len(session.actions) == 1


def test_a_close_then_renegotiation_keeps_pointer_and_replays_the_restore_token() -> None:
    session = _FakePortalSession(restore_token="tok-1")
    sink = portal.DeferredPortalPointerSink(session)
    session.ensure_started(1.0)
    sink.move_relative(1.0, 0.0)
    assert portal.read_token() == "tok-1"

    session.close()  # the idle reaper, or a bus drop
    session.calls.clear()
    session.ensure_started(1.0)

    options = session.select_options()
    assert options["types"] == ("u", KEYBOARD_AND_POINTER)
    assert options["restore_token"] == ("s", "tok-1")
    assert options["persist_mode"] == ("u", portal.PERSIST_UNTIL_REVOKED)
    sink.move_relative(2.0, 0.0)  # the sink re-derives on the new generation
    assert len(session.actions) == 2


# --------------------------------------------------------------------------- #
# ADR-v2-146 rule 7: a dictation-only install is byte-identical
# --------------------------------------------------------------------------- #
def test_a_dictation_only_negotiation_is_exactly_the_keyboard_negotiation() -> None:
    session = _FakePortalSession()
    portal.PortalInjector(session=session).warm()

    assert session.members == ["CreateSession", "SelectDevices", "Start"]
    assert session.select_options() == {
        "types": ("u", portal.DEVICE_KEYBOARD),
        "persist_mode": ("u", portal.PERSIST_UNTIL_REVOKED),
    }
    start = [body for member, _, body in session.calls if member == "Start"][0]
    assert start == (session._session_handle, "", {})
    assert session.pointer_granted is False
    assert session._pointer_consumers == 0
