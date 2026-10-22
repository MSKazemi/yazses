"""The keyboard and the pointer share ONE portal connection -- what that costs (#403).

ADR-v2-146 rule 6 put the Wayland pointer on the RemoteDesktop session dictation already
types through, so there is one consent dialog and one restore token. The price of sharing
is that two producers now write to one D-Bus connection from two threads: dictation types
on the daemon's thread while the Head-Pointer moves on the perception thread. The
connection is a `jeepney.io.blocking.DBusConnection`, whose `send` is a bare
`sock.sendall` with no lock -- jeepney ships `jeepney.io.threading` precisely as the
"synchronous IO wrappers with thread safety" variant. These tests hold three lines:

1. **No two messages are ever in flight at once**, whichever threads send them.
2. **The keyboard's wire is byte-identical** whether or not a pointer consumer is on the
   session, and identical to the message the pre-pointer keyboard path built -- the
   proof that adding the pointer did not change dictation.
3. **A grant the compositor really gave is not thrown away** because the consumer that
   asked for it left while the dialog was open.

What they cannot prove is what every test in this area cannot: `Notify*` is fire-and-forget,
so nothing here shows that a key was typed or a pointer moved. That is the live Wayland
smoke report's job (`design/eye-control/TEST_PLAN.md`).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from tests.test_pointer_portal import KEYBOARD_AND_POINTER, _FakeConnection, _FakePortalSession
from yazses.inject import portal
from yazses.pointer.base import PointerBackendError

JOIN_S = 10.0


@pytest.fixture(autouse=True)
def _sandboxed(tmp_path, monkeypatch):
    """No restore token is read from, or written to, the developer's own data dir."""
    monkeypatch.setenv("YAZSES_DATA_DIR", str(tmp_path))
    # Zero key delay: these tests are about which bytes go out and in what order, and
    # the default 4 ms per event would only make them slow.
    monkeypatch.setenv("YAZSES_PORTAL_KEY_DELAY", "0")


# --------------------------------------------------------------------------- #
# 1. One message at a time on the one connection.
# --------------------------------------------------------------------------- #
class _OverlapDetectingSession(_FakePortalSession):
    """Records how many sends were inside the connection at the same moment.

    The short sleep stands in for a `sendall` that wrote part of its message and is
    waiting to write the rest -- the window in which a second thread's bytes would land
    in the middle of the first message on a real socket.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._inside = 0
        self._inside_guard = threading.Lock()
        self.max_inside = 0

    def _send_notify(self, member: str, signature: str, body: tuple) -> None:
        with self._inside_guard:
            self._inside += 1
            self.max_inside = max(self.max_inside, self._inside)
        try:
            time.sleep(0.0005)
            super()._send_notify(member, signature, body)
        finally:
            with self._inside_guard:
                self._inside -= 1


def test_dictation_and_the_pointer_never_write_to_the_connection_at_once() -> None:
    session = _OverlapDetectingSession()
    injector = portal.PortalInjector(session=session)
    sink = injector.pointer_sink(start_timeout=1.0)
    text = "dictation keeps typing while the head moves " * 2
    moves = 120
    start = threading.Barrier(2)
    errors: list[BaseException] = []

    def _type() -> None:
        try:
            start.wait(JOIN_S)
            injector.inject(text)
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    def _point() -> None:
        try:
            start.wait(JOIN_S)
            for _ in range(moves):
                sink.move_relative(1.0, -1.0)
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=_type), threading.Thread(target=_point)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_S)
        assert not thread.is_alive(), "a producer hung on the shared connection"
    assert errors == []

    assert session.max_inside == 1, (
        f"{session.max_inside} messages were in flight on one connection at once; "
        "on a real socket their bytes interleave and the bus drops the client"
    )
    keyboard = [body for member, _, body in session.notified if member == "NotifyKeyboardKeysym"]
    pointer = [body for member, _, body in session.notified if member == "NotifyPointerMotion"]
    assert len(pointer) == moves
    # Interleaving with the pointer must not reorder or lose a single keystroke.
    expected = []
    for char in text:
        keysym = portal.char_to_keysym(char)
        expected += [(keysym, portal.KEY_PRESSED), (keysym, portal.KEY_RELEASED)]
    assert [(body[2], body[3]) for body in keyboard] == expected


def test_the_send_lock_is_never_held_across_a_keystroke_delay(monkeypatch) -> None:
    """Per message, not per tap: the keyboard keeps its timing and never stalls the pointer.

    Held across `tap`'s sleep, the lock would make every pointer event wait out a key
    delay -- and make a slow `YAZSES_PORTAL_KEY_DELAY` into a laggy pointer.
    """
    monkeypatch.setenv("YAZSES_PORTAL_KEY_DELAY", "0.001")
    session = _FakePortalSession()
    injector = portal.PortalInjector(session=session)
    injector.pointer_sink(start_timeout=1.0)

    held_during_sleep: list[bool] = []
    real_sleep = portal.time.sleep

    def _watching_sleep(seconds: float) -> None:
        held_during_sleep.append(session._send_lock.locked())
        real_sleep(0)

    monkeypatch.setattr(portal.time, "sleep", _watching_sleep)
    injector.inject("ab")

    assert held_during_sleep, "the key delay never ran, so this test proved nothing"
    assert not any(held_during_sleep)


# --------------------------------------------------------------------------- #
# 2. The keyboard's wire is unchanged by the pointer.
# --------------------------------------------------------------------------- #
_HANDLE = "/org/freedesktop/portal/desktop/session/7"


class _RecordingConnection(_FakeConnection):
    """A connection that keeps each real jeepney `Message` instead of writing it."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[Any] = []

    def send(self, msg: Any) -> None:
        self.sent.append(msg)


def _started_session(*, with_pointer: bool) -> tuple[portal._PortalSession, _RecordingConnection]:
    """A real `_PortalSession` already past `Start`, with the bus replaced by a recorder.

    Only `_conn` is swapped: `notify_keysym`, `_notify` and `_send_notify` are the shipped
    code, so jeepney builds the very messages a user's desktop would receive.
    """
    session = portal._PortalSession()
    conn = _RecordingConnection()
    session._conn = conn
    session._session_handle = _HANDLE
    session._negotiated = True
    if with_pointer:
        session._pointer_consumers = 1
        session._asked_pointer = True
        session._pointer_granted = True
    return session, conn


def _dictate(injector: portal.PortalInjector) -> None:
    """One of each keyboard entry point, with characters from three keysym ranges."""
    injector.inject("Hé→\n")
    injector.inject_backspaces(2)
    injector.inject_key_sequence(["ctrl+shift+a", "enter"])


def _wire(messages: list[Any]) -> list[bytes]:
    return [msg.serialise(serial=serial) for serial, msg in enumerate(messages, start=1)]


def test_the_keyboard_wire_is_byte_identical_with_the_pointer_on_the_session() -> None:
    pytest.importorskip("jeepney", reason="the D-Bus client is a Linux/BSD dependency")

    alone, alone_conn = _started_session(with_pointer=False)
    shared, shared_conn = _started_session(with_pointer=True)
    _dictate(portal.PortalInjector(session=alone))
    sink = portal.PortalPointerSink(shared)
    injector = portal.PortalInjector(session=shared)
    sink.move_relative(5.0, 5.0)  # pointer traffic before ...
    _dictate(injector)
    sink.click()  # ... and after the dictation, on the same connection

    keyboard_only = [
        msg for msg in shared_conn.sent if msg.header.fields[3] == "NotifyKeyboardKeysym"
    ]
    assert len(keyboard_only) == len(alone_conn.sent) > 0
    assert _wire(keyboard_only) == _wire(alone_conn.sent)


def test_the_keyboard_wire_is_the_message_the_pre_pointer_path_built() -> None:
    """Pinned against an independently spelled message, not against the code under test.

    Every literal below is written out rather than read from `portal`, so a change to the
    bus name, object path, interface, member, signature or body shape of a keystroke --
    the thing a pointer refactor could most plausibly disturb -- is a red test here.
    """
    pytest.importorskip("jeepney", reason="the D-Bus client is a Linux/BSD dependency")
    from jeepney import DBusAddress, new_method_call

    session, conn = _started_session(with_pointer=True)
    portal.PortalInjector(session=session).inject("a")

    address = DBusAddress(
        "/org/freedesktop/portal/desktop",
        bus_name="org.freedesktop.portal.Desktop",
        interface="org.freedesktop.portal.RemoteDesktop",
    )
    expected = [
        new_method_call(address, "NotifyKeyboardKeysym", "oa{sv}iu", (_HANDLE, {}, 0x61, 1)),
        new_method_call(address, "NotifyKeyboardKeysym", "oa{sv}iu", (_HANDLE, {}, 0x61, 0)),
    ]
    assert _wire(conn.sent) == _wire(expected)


# --------------------------------------------------------------------------- #
# 3. A real grant survives its requester leaving mid-dialog.
# --------------------------------------------------------------------------- #
class _ConsumerLeavesDuringDialog(_FakePortalSession):
    """Runs ``on_start`` while `Start` is pending -- the user is still reading the dialog."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.on_start: Any = None

    def _call_with_response(self, member, signature, body, timeout):
        if member == "Start" and self.on_start is not None:
            self.on_start()
        return super()._call_with_response(member, signature, body, timeout)


def test_a_grant_given_after_its_requester_left_still_serves_the_next_consumer() -> None:
    session = _ConsumerLeavesDuringDialog()
    first = portal.DeferredPortalPointerSink(session)
    session.on_start = first.close  # e.g. the Head-Pointer toggled off mid-dialog
    session.ensure_started(1.0)

    assert session.select_options()["types"] == ("u", KEYBOARD_AND_POINTER)
    assert session._pointer_consumers == 0
    assert session.pointer_granted is True, (
        "the compositor granted POINTER; discarding it because nobody was registered "
        "at that instant leaves the next consumer refused for a dialog it already passed"
    )

    second = portal.DeferredPortalPointerSink(session)  # must not raise "keyboard alone"
    second.move_relative(1.0, 0.0)
    assert len(session.actions) == 1
    assert session.members.count("Start") == 1, "no second dialog"


def test_a_keyboard_only_mask_is_still_never_read_as_a_pointer_grant() -> None:
    """The other direction of the same change: asked-for gates granted, both ways.

    A portal that answers `Start` with a pointer bit nobody asked for -- the fake's
    default answer -- must not make a dictation-only session look pointer-capable.
    """
    session = _FakePortalSession(granted=KEYBOARD_AND_POINTER)
    portal.PortalInjector(session=session).warm()

    assert session.select_options()["types"] == ("u", portal.DEVICE_KEYBOARD)
    assert session.pointer_granted is False
    with pytest.raises(PointerBackendError, match="keyboard"):
        portal.DeferredPortalPointerSink(session)
