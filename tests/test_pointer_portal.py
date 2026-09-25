"""The Wayland pointer: one RemoteDesktop session, shared with the keyboard (#403).

`yazses.inject.portal` already negotiates an XDG RemoteDesktop session so a confined snap
can type on Wayland. ADR-v2-146 rule 6 says the pointer extends *that* session, and these
tests are what holds the line: a second D-Bus client would mean a second consent dialog, a
second restore token and two grants competing, and none of that is visible in a diff.

**The D-Bus layer is injected, not mocked at the socket.** `_FakePortalSession` is a real
`portal._PortalSession` with exactly three seams replaced — the bus connection, the
request/response call, and the fire-and-forget notify — so the negotiation logic under
test (device mask, restore token, ordering, granted-device parsing) is the shipped code,
while CI needs no compositor, no session bus and no permission dialog. Every notify is
recorded as a `PointerAction`, which is what lets this backend inherit the shared
`PointerSinkContract` instead of describing the contract a second time in its own dialect.

**What these tests cannot prove.** The portal's `Notify*` methods are fire-and-forget: a
send that raises nothing is not evidence that a pointer moved. A compositor that ignores
the event and one that acts on it are indistinguishable from the client, which is the same
shape of failure as the `ydotool 0.1.8` dialect that printed an error and exited 0 while
injection was dead for a year. So the asserted claims here are "the right method, with the
right signature and the right values, at the right moment, and never before consent" —
never "the pointer moved". That needs the live smoke report `design/eye-control/TEST_PLAN.md`
asks for.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.pointer_contract import PointerSinkContract
from tests.pointer_fake import PointerAction
from yazses.inject import portal
from yazses.pointer.base import (
    PointerBackendError,
    PointerButton,
    PointerSink,
    PointerUnsupportedError,
)

KEYBOARD_AND_POINTER = portal.DEVICE_KEYBOARD | portal.DEVICE_POINTER

_BUTTON_BY_CODE = {code: button for button, code in portal.POINTER_BUTTON_CODES.items()}


class _FakeConnection:
    """Stands in for the jeepney session-bus connection. Opens nothing."""

    unique_name = ":1.42"

    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class _FakePortalSession(portal._PortalSession):
    """A real session with its three D-Bus seams replaced by recorders.

    ``granted`` is the device mask the fake portal answers `Start` with, which is how a
    compositor that hands back only the keyboard is modelled. ``refuse`` names a method
    the user cancels, raising exactly what the real `_call_with_response` raises on a
    non-zero response code.
    """

    def __init__(
        self,
        *,
        granted: int | None = KEYBOARD_AND_POINTER,
        refuse: str = "",
        restore_token: str = "fresh-token",
    ) -> None:
        super().__init__()
        self.granted = granted
        self.refuse = refuse
        self.restore_token = restore_token
        #: ``(member, signature, body)`` for each negotiation call, in order.
        self.calls: list[tuple[str, str, tuple]] = []
        #: ``(member, signature, body)`` for each input event sent.
        self.notified: list[tuple[str, str, tuple]] = []
        #: The pointer events, translated into the shared contract's vocabulary.
        self.actions: list[PointerAction] = []
        self.connections = 0
        #: 1-based indices of `_send_notify` calls that must fail, and a failure that
        #: persists until it is cleared (what the contract's `induce_failure` needs).
        self.raise_on_call: set[int] = set()
        self.persistent_failure: Exception | None = None
        self._sends = 0

    # -- the replaced seams ------------------------------------------------

    def _open_connection(self) -> Any:
        self.connections += 1
        return _FakeConnection()

    def _call_with_response(
        self, member: str, signature: str, body: tuple, timeout: float
    ) -> dict:
        self.calls.append((member, signature, body))
        if member == self.refuse:
            raise portal.PortalUnavailable(
                f"{member} was refused by the portal (response code 1; "
                "1 means the user cancelled the permission dialog)"
            )
        if member == "CreateSession":
            return {"session_handle": ("o", "/org/freedesktop/portal/desktop/session/1")}
        if member == "Start":
            started: dict = {"restore_token": ("s", self.restore_token)}
            if self.granted is not None:
                started["devices"] = ("u", self.granted)
            return started
        return {}

    def _send_notify(self, member: str, signature: str, body: tuple) -> None:
        self._sends += 1
        if self.persistent_failure is not None:
            raise self.persistent_failure
        if self._sends in self.raise_on_call:
            raise OSError(f"fake bus refused send {self._sends}")
        self.notified.append((member, signature, body))
        action = _as_action(member, body)
        if action is not None:
            self.actions.append(action)

    # -- helpers -----------------------------------------------------------

    @property
    def members(self) -> list[str]:
        return [member for member, _, _ in self.calls]

    def select_options(self) -> dict:
        """The options dict of the single `SelectDevices` call."""
        selects = [body[-1] for member, _, body in self.calls if member == "SelectDevices"]
        assert len(selects) == 1, f"expected one SelectDevices, got {len(selects)}"
        return dict(selects[0])


def _as_action(member: str, body: tuple) -> PointerAction | None:
    """Translate one portal notify into the contract's `PointerAction` vocabulary."""
    if member == "NotifyPointerMotion":
        return PointerAction.move_relative(body[2], body[3])
    if member == "NotifyPointerAxis":
        return PointerAction.scroll(body[2], body[3])
    if member == "NotifyPointerButton":
        button = _BUTTON_BY_CODE[body[2]]
        if body[3] == portal.BUTTON_PRESSED:
            return PointerAction.press(button)
        return PointerAction.release(button)
    return None


def _open(session: _FakePortalSession) -> portal.PortalPointerSink:
    return portal.open_pointer_sink(session, start_timeout=1.0)


@pytest.fixture(autouse=True)
def sandboxed_token(tmp_path, monkeypatch):
    """No test here reads or writes the developer's own restore token."""
    monkeypatch.setenv("YAZSES_DATA_DIR", str(tmp_path))
    return tmp_path


# --------------------------------------------------------------------------- #
# The shared contract, against the portal backend.
# --------------------------------------------------------------------------- #
class TestPortalPointerSink(PointerSinkContract):
    """The whole `PointerSink` contract, inherited rather than re-described."""

    def setup_method(self) -> None:
        self._sessions: dict[int, _FakePortalSession] = {}

    def make_sink(self) -> portal.PortalPointerSink:
        session = _FakePortalSession()
        sink = _open(session)
        self._sessions[id(sink)] = session
        return sink

    def _session_of(self, sink: PointerSink) -> _FakePortalSession:
        return self._sessions[id(sink)]

    def recorded(self, sink: PointerSink) -> list[PointerAction]:
        return list(self._session_of(sink).actions)

    def induce_failure(self, sink: PointerSink) -> None:
        self._session_of(sink).persistent_failure = OSError("the session bus went away")

    def clear_failure(self, sink: PointerSink) -> None:
        self._session_of(sink).persistent_failure = None


# --------------------------------------------------------------------------- #
# One session, and POINTER only when something asked for it.
# --------------------------------------------------------------------------- #
def test_a_dictation_only_session_never_asks_for_the_pointer() -> None:
    """ADR-v2-146 rule 7. An install with no pointer consumer is unchanged."""
    session = _FakePortalSession()
    session.ensure_started(1.0)
    assert session.select_options()["types"] == ("u", portal.DEVICE_KEYBOARD)
    assert session.pointer_granted is False


def test_a_pointer_consumer_joins_the_one_select_devices_call() -> None:
    session = _FakePortalSession()
    sink = _open(session)

    assert session.select_options()["types"] == ("u", KEYBOARD_AND_POINTER)
    assert session.members == ["CreateSession", "SelectDevices", "Start"]
    assert session.connections == 1
    assert sink.capabilities().backend == "portal"


def test_a_second_consumer_opens_no_second_session() -> None:
    """Two sinks, one grant: the count is bookkeeping, not another negotiation."""
    session = _FakePortalSession()
    first = _open(session)
    second = _open(session)

    assert session.members.count("CreateSession") == 1
    assert session.members.count("Start") == 1
    assert session.connections == 1
    first.close()
    # The surviving sink still works; releasing one consumer is not a revocation.
    second.move_relative(1.0, 0.0)
    assert session.actions == [PointerAction.move_relative(1.0, 0.0)]


def test_the_injector_hands_out_a_sink_on_its_own_session() -> None:
    """The quotable path: the pointer rides the session that types."""
    session = _FakePortalSession()
    injector = portal.PortalInjector(session=session)
    sink = injector.pointer_sink(start_timeout=1.0)

    injector.inject("a")
    sink.move_relative(2.0, 3.0)

    assert session.connections == 1
    assert session.members.count("CreateSession") == 1
    assert [member for member, _, _ in session.notified] == [
        "NotifyKeyboardKeysym",
        "NotifyKeyboardKeysym",
        "NotifyPointerMotion",
    ], "keyboard and pointer must leave through the same session"


def test_the_keyboard_keeps_working_after_the_pointer_is_added() -> None:
    session = _FakePortalSession()
    injector = portal.PortalInjector(session=session)
    injector.pointer_sink(start_timeout=1.0)

    injector.inject("Z")
    keysyms = [body[2] for member, _, body in session.notified if "Keyboard" in member]
    assert keysyms == [0x5A, 0x5A]


def test_a_started_keyboard_only_session_refuses_rather_than_re_prompting() -> None:
    """The conservative branch: no second dialog mid-sentence, and no silent no-op."""
    session = _FakePortalSession()
    session.ensure_started(1.0)  # dictation warmed it, keyboard only

    with pytest.raises(PointerBackendError, match="restart"):
        _open(session)

    assert session.members.count("Start") == 1, "it must not re-negotiate behind us"
    assert session.notified == []


def test_releasing_the_last_consumer_narrows_the_next_negotiation() -> None:
    session = _FakePortalSession()
    sink = _open(session)
    sink.close()
    session.close()

    session.calls.clear()
    session.ensure_started(1.0)
    assert session.select_options()["types"] == ("u", portal.DEVICE_KEYBOARD)


# --------------------------------------------------------------------------- #
# Nothing before consent; refusal is explicit.
# --------------------------------------------------------------------------- #
def test_no_pointer_event_is_sent_before_the_session_starts() -> None:
    session = _FakePortalSession()
    assert session.notified == []
    sink = _open(session)
    assert session.notified == [], "opening a sink must emit no input"
    sink.move_relative(1.0, 1.0)
    assert len(session.notified) == 1


@pytest.mark.parametrize("refused", ["CreateSession", "SelectDevices", "Start"])
def test_a_cancelled_dialog_is_a_clean_unavailable_and_no_action(refused: str) -> None:
    session = _FakePortalSession(refuse=refused)

    with pytest.raises(PointerBackendError):
        _open(session)

    assert session.notified == [], "a refusal must not be followed by events"
    # The consumer is handed back, so a later dictation-only negotiation stays narrow.
    session.calls.clear()
    session.refuse = ""
    session.ensure_started(1.0)
    assert session.select_options()["types"] == ("u", portal.DEVICE_KEYBOARD)


@pytest.mark.parametrize("refused", ["SelectDevices", "Start"])
def test_a_refusal_after_create_session_leaves_no_half_open_session(refused: str) -> None:
    """Found while writing the pointer path, and it bites the keyboard too.

    `CreateSession` completes before the dialog is raised, so a user who clicks Cancel
    left `_session_handle` set — and `ensure_started` returns early on a non-empty
    handle, so from then on every keystroke was notified at a session the compositor
    never authorised, with nothing raised and nothing typed. A negotiation that did not
    finish must be indistinguishable from one that never started.
    """
    session = _FakePortalSession(refuse=refused)
    with pytest.raises(portal.PortalUnavailable):
        session.ensure_started(1.0)

    assert session._session_handle == ""
    assert session._conn is None

    # The proof that it is not merely cosmetic: the next attempt really negotiates.
    session.refuse = ""
    session.calls.clear()
    session.ensure_started(1.0)
    assert session.members == ["CreateSession", "SelectDevices", "Start"]
    assert session._session_handle


def test_a_cancelled_pointer_dialog_leaves_dictation_alone() -> None:
    """Denial must not cost the user their keyboard."""
    session = _FakePortalSession(refuse="Start")
    injector = portal.PortalInjector(session=session)
    with pytest.raises(PointerBackendError):
        injector.pointer_sink(start_timeout=1.0)

    session.refuse = ""
    injector.inject("a")
    assert [member for member, _, _ in session.notified] == [
        "NotifyKeyboardKeysym",
        "NotifyKeyboardKeysym",
    ]


# --------------------------------------------------------------------------- #
# Capability is discovered from the Start response, never assumed.
# --------------------------------------------------------------------------- #
def test_a_keyboard_only_grant_is_unsupported_not_silent() -> None:
    """The compositor said pointer: no. That is an error, not a pointer that never moves."""
    session = _FakePortalSession(granted=portal.DEVICE_KEYBOARD)

    with pytest.raises(PointerUnsupportedError, match="did not grant"):
        _open(session)

    assert session.pointer_granted is False
    assert session.notified == []


def test_a_start_response_without_a_device_mask_is_not_read_as_a_grant() -> None:
    """Asked-for is not granted. Absent evidence is treated as no evidence."""
    session = _FakePortalSession(granted=None)

    with pytest.raises(PointerUnsupportedError):
        _open(session)


def test_the_grant_survives_only_while_the_session_does() -> None:
    session = _FakePortalSession()
    assert session.pointer_granted is False
    _open(session)
    assert session.pointer_granted is True
    session.close()
    assert session.pointer_granted is False


def test_a_sink_whose_session_closed_refuses_instead_of_re_prompting() -> None:
    """The idle reaper closes the session between gestures; that is not a new dialog."""
    session = _FakePortalSession()
    sink = _open(session)
    sink.move_relative(1.0, 1.0)
    session.close()

    with pytest.raises(PointerBackendError, match="closed"):
        sink.move_relative(1.0, 1.0)
    assert session.members.count("Start") == 1
    assert len(session.notified) == 1


def test_pointer_use_counts_as_use_for_the_idle_reaper() -> None:
    """Otherwise the session is closed under a user who moves but does not dictate."""
    session = _FakePortalSession()
    sink = _open(session)
    assert session._last_used is None
    sink.move_relative(1.0, 1.0)
    assert session._last_used is not None


# --------------------------------------------------------------------------- #
# The wire: members, signatures, values.
# --------------------------------------------------------------------------- #
def test_relative_motion_is_one_notify_pointer_motion_with_doubles() -> None:
    session = _FakePortalSession()
    sink = _open(session)
    sink.move_relative(3, -4.5)

    member, signature, body = session.notified[0]
    assert member == "NotifyPointerMotion"
    assert signature == "oa{sv}dd"
    handle, options, dx, dy = body
    assert handle == "/org/freedesktop/portal/desktop/session/1"
    assert options == {}
    assert (dx, dy) == (3.0, -4.5)
    assert isinstance(dx, float) and isinstance(dy, float)


def test_buttons_are_evdev_codes_pressed_then_released() -> None:
    """X11's numbering would put a right-click on the middle button."""
    expected = {
        PointerButton.LEFT: 0x110,
        PointerButton.RIGHT: 0x111,
        PointerButton.MIDDLE: 0x112,
    }
    for button, code in expected.items():
        session = _FakePortalSession()
        _open(session).click(button)
        assert [(m, s) for m, s, _ in session.notified] == [
            ("NotifyPointerButton", "oa{sv}iu"),
            ("NotifyPointerButton", "oa{sv}iu"),
        ]
        assert [(b[2], b[3]) for _, _, b in session.notified] == [
            (code, portal.BUTTON_PRESSED),
            (code, portal.BUTTON_RELEASED),
        ]


def test_scroll_is_notify_pointer_axis_with_the_signs_untouched() -> None:
    """+dy is down at the boundary and +dy is down on the portal: no negation."""
    session = _FakePortalSession()
    sink = _open(session)
    sink.scroll(0.0, 1.0)
    sink.scroll(0.0, -1.0)
    sink.scroll(2.0, 0.0)

    assert [(m, s) for m, s, _ in session.notified] == [("NotifyPointerAxis", "oa{sv}dd")] * 3
    assert [(b[2], b[3]) for _, _, b in session.notified] == [
        (0.0, 1.0),
        (0.0, -1.0),
        (2.0, 0.0),
    ]


def test_absolute_motion_is_refused_with_a_reason_and_sends_nothing() -> None:
    session = _FakePortalSession()
    sink = _open(session)
    with pytest.raises(PointerUnsupportedError, match="absolute"):
        sink.move_absolute(100.0, 200.0)
    assert session.notified == []
    assert sink.capabilities().absolute_motion is False


def test_the_capability_record_matches_what_the_backend_actually_does() -> None:
    caps = portal.PORTAL_POINTER_CAPABILITIES
    assert caps.backend == "portal"
    assert caps.relative_motion and caps.scroll_vertical and caps.scroll_horizontal
    assert caps.buttons == frozenset(PointerButton)
    assert not caps.absolute_motion


def test_the_real_dbus_messages_serialise_with_these_signatures() -> None:
    """The one test that lets jeepney see the bodies.

    Everything above replaces `_send_notify`, so a signature that does not match its body
    would pass — `"oa{sv}dd"` with an int where a double belongs is caught at
    serialisation, on a user's desktop, not here. This drives the *real* method through a
    connection that records instead of writing to a socket, and serialises the result.
    """
    pytest.importorskip("jeepney", reason="the D-Bus client is a Linux/BSD dependency")

    sent: list[Any] = []

    class _RecordingConn(_FakeConnection):
        def send(self, msg: Any) -> None:
            sent.append(msg)

    session = portal._PortalSession()
    session._conn = _RecordingConn()
    session._session_handle = "/org/freedesktop/portal/desktop/session/9"

    session.notify_pointer_motion(1, -2)
    session.notify_pointer_button(portal.BTN_LEFT, portal.BUTTON_PRESSED)
    session.notify_pointer_axis(0.0, 3.0)

    members = [m.header.fields[3] for m in sent]  # HeaderFields.member
    assert members == ["NotifyPointerMotion", "NotifyPointerButton", "NotifyPointerAxis"]
    for serial, msg in enumerate(sent, start=1):
        assert msg.serialise(serial=serial), "a signature/body mismatch would raise here"


# --------------------------------------------------------------------------- #
# Failure behaviour beyond the shared contract.
# --------------------------------------------------------------------------- #
def test_a_failed_release_still_tries_to_lift_the_button() -> None:
    """A button left down is a desktop stuck in a drag, for a user who may have no mouse."""
    session = _FakePortalSession()
    sink = _open(session)
    session.raise_on_call = {2}  # the release fails; the retry does not

    with pytest.raises(PointerBackendError, match="click the left button"):
        sink.click()

    assert session.actions == [
        PointerAction.press(PointerButton.LEFT),
        PointerAction.release(PointerButton.LEFT),
    ], "the recovery release must have reached the portal"


def test_a_failed_press_sends_no_release() -> None:
    session = _FakePortalSession()
    sink = _open(session)
    session.raise_on_call = {1}

    with pytest.raises(PointerBackendError):
        sink.click(PointerButton.RIGHT)

    assert session.actions == [], "nothing was pressed, so nothing may be released"


def test_a_bus_failure_is_a_backend_error_not_an_unsupported_one() -> None:
    """The distinction the caller acts on: retryable versus permanent."""
    session = _FakePortalSession()
    sink = _open(session)
    session.persistent_failure = OSError("broken pipe")

    with pytest.raises(PointerBackendError) as excinfo:
        sink.move_relative(1.0, 1.0)
    assert not isinstance(excinfo.value, PointerUnsupportedError)
    assert "broken pipe" in str(excinfo.value)


def test_closing_the_sink_leaves_the_session_typing() -> None:
    """The sink borrows the session; it must not end the user's ability to type."""
    session = _FakePortalSession()
    injector = portal.PortalInjector(session=session)
    sink = injector.pointer_sink(start_timeout=1.0)
    sink.close()
    sink.close()  # idempotent

    injector.inject("a")
    assert [member for member, _, _ in session.notified] == [
        "NotifyKeyboardKeysym",
        "NotifyKeyboardKeysym",
    ]
    assert session._session_handle, "the shared session must still be open"


# --------------------------------------------------------------------------- #
# Restore-token behaviour is unchanged by the pointer.
# --------------------------------------------------------------------------- #
def test_the_restore_token_is_offered_and_saved_exactly_as_before(sandboxed_token) -> None:
    portal.write_token("token-from-last-time")
    session = _FakePortalSession(restore_token="token-for-next-time")
    _open(session)

    options = session.select_options()
    assert options["restore_token"] == ("s", "token-from-last-time")
    assert options["persist_mode"] == ("u", portal.PERSIST_UNTIL_REVOKED)
    assert portal.read_token() == "token-for-next-time"


def test_a_pointer_grant_does_not_change_where_the_token_lives(sandboxed_token) -> None:
    session = _FakePortalSession()
    _open(session)
    assert (sandboxed_token / portal.TOKEN_FILENAME).exists()


# --------------------------------------------------------------------------- #
# The consent copy stays true once the pointer is in the request.
# --------------------------------------------------------------------------- #
def test_the_pointer_consent_copy_does_not_claim_the_mouse_is_excluded() -> None:
    """The keyboard-only copy says "no mouse". Reusing it here would be a false claim."""
    _, body = portal.consent_explanation(wants_pointer=True)
    assert "no mouse" not in body
    assert "pointer" in body
    assert "no screen capture" in body and "nothing sent anywhere" in body


def test_the_pointer_consent_copy_survives_a_balloon_that_drops_long_text() -> None:
    for can_avoid in (True, False):
        title, body = portal.consent_explanation(
            can_avoid=can_avoid, wants_pointer=True
        )
        assert len(body) <= 256, f"body is {len(body)} chars"
        assert "Remote Desktop" in title and "Remote Desktop" in body
        assert body.index("no screen capture") < body.index("Remote Desktop")


def test_the_keyboard_only_copy_is_untouched() -> None:
    """The dictation path's wording is the tested, shipped one; the default is it."""
    assert portal.consent_explanation() == portal.consent_explanation(
        wants_pointer=False
    )
    _, body = portal.consent_explanation()
    assert "no mouse" in body
