"""A restore token answers only for what the user was asked when it was issued (#403).

GNOME's portal backend (`restore_from_data` in `xdg-desktop-portal-gnome`) starts a restored
session with the device mask *stored with the token*, shows no dialog, and ignores the mask in
the new `SelectDevices`. So a user who approved typing first and enabled a pointer feature
later was handed the keyboard alone on every start. KDE compares the two masks and asks again
by itself.

`_GnomePortalSession` models the GNOME rule on top of the fake in
`tests/test_pointer_portal.py`; the negotiation under test is the shipped code. It is a model
read from the portal's source, not a compositor.
"""
from __future__ import annotations

import types
import uuid

import pytest

from tests.pointer_fake import PointerAction
from tests.test_pointer_portal import KEYBOARD_AND_POINTER, _FakePortalSession
from yazses.core.daemon import Daemon
from yazses.inject import portal
from yazses.pointer.base import PointerUnsupportedError
from yazses.system import notify as notify_mod

KEYBOARD = portal.DEVICE_KEYBOARD


@pytest.fixture(autouse=True)
def sandboxed_token(tmp_path, monkeypatch):
    """No test here reads or writes the developer's own restore token."""
    monkeypatch.setenv("YAZSES_DATA_DIR", str(tmp_path))
    return tmp_path


class _GnomePortalSession(_FakePortalSession):
    """Restores the stored grant when a known token is offered; otherwise "asks".

    ``store`` maps token to device mask and outlives a session, as the permission store
    outlives a daemon. ``answer`` is what the user grants in a dialog (``None``: all that
    was asked for). ``dialogs`` records the mask each dialog asked for.
    """

    def __init__(
        self, store: dict[str, int], *, answer: int | None = None, refuse: str = ""
    ) -> None:
        super().__init__(refuse=refuse)
        self.store = store
        self.answer_mask = answer
        self.dialogs: list[int] = []

    def _call_with_response(
        self, member: str, signature: str, body: tuple, timeout: float
    ) -> dict:
        result = super()._call_with_response(member, signature, body, timeout)
        if member != "Start":
            return result
        options = [b[-1] for m, _, b in self.calls if m == "SelectDevices"][-1]
        offered = options.get("restore_token", ("s", ""))[1]
        if offered in self.store:
            granted = self.store.pop(offered)  # single use
        else:
            asked = options["types"][1]
            self.dialogs.append(asked)
            granted = asked if self.answer_mask is None else self.answer_mask
        token = f"token-{uuid.uuid4().hex}"
        self.store[token] = granted
        return {"restore_token": ("s", token), "devices": ("u", granted)}


def _dictation_only_run(store: dict[str, int]) -> None:
    session = _GnomePortalSession(store)
    session.ensure_started(1.0)
    session.close()


def _selects(session: _FakePortalSession) -> list[dict]:
    return [dict(body[-1]) for m, _, body in session.calls if m == "SelectDevices"]


# --------------------------------------------------------------------------- #
# The upgrade path: typing first, pointer later
# --------------------------------------------------------------------------- #
def test_enabling_the_pointer_after_typing_asks_once_and_is_granted() -> None:
    store: dict[str, int] = {}
    _dictation_only_run(store)

    first = _GnomePortalSession(store)
    sink = portal.open_pointer_sink(first, start_timeout=1.0)
    sink.move_relative(1.0, 0.0)

    assert first.dialogs == [KEYBOARD_AND_POINTER]
    assert "restore_token" not in first.select_options()
    assert first.actions == [PointerAction.move_relative(1.0, 0.0)]

    second = _GnomePortalSession(store)
    portal.open_pointer_sink(second, start_timeout=1.0)
    assert second.dialogs == [], "the new approval is remembered"
    assert "restore_token" in second.select_options()


def test_a_cancelled_widening_dialog_gives_dictation_its_old_grant_back() -> None:
    store: dict[str, int] = {}
    _dictation_only_run(store)
    saved = portal.read_token()

    session = _GnomePortalSession(store, refuse="Start")
    sink = portal.DeferredPortalPointerSink(session)
    assert portal.PortalInjector(session).warm() is False
    assert portal.read_token() == saved, "a refused ask must not lose the approval"

    session.refuse = ""
    session.calls.clear()
    portal.PortalInjector(session).inject("a")

    assert session.select_options()["restore_token"] == ("s", saved)
    assert session.dialogs == [], "no dialog in the middle of a dictation"
    assert len(session.notified) == 2
    with pytest.raises(PointerUnsupportedError):
        sink.move_relative(1.0, 0.0)
    assert session.actions == []


def test_the_next_process_asks_again_after_a_cancelled_dialog() -> None:
    store: dict[str, int] = {}
    _dictation_only_run(store)
    cancelled = _GnomePortalSession(store, refuse="Start")
    portal.DeferredPortalPointerSink(cancelled)
    assert portal.PortalInjector(cancelled).warm() is False
    # Dictation restores the keyboard grant in the same process, with the pointer
    # consumer still registered...
    cancelled.refuse = ""
    cancelled.calls.clear()
    cancelled.ensure_started(1.0)
    assert cancelled.select_options()["types"] == ("u", KEYBOARD_AND_POINTER)
    cancelled.close()

    # ...which must not be recorded as an answer about the pointer.
    assert portal.token_devices(portal.read_token()) == KEYBOARD
    restarted = _GnomePortalSession(store)
    portal.open_pointer_sink(restarted, start_timeout=1.0)
    assert restarted.dialogs == [KEYBOARD_AND_POINTER]


def test_a_user_who_leaves_the_pointer_out_is_not_asked_again() -> None:
    store: dict[str, int] = {}
    _dictation_only_run(store)
    declined = _GnomePortalSession(store, answer=KEYBOARD)
    with pytest.raises(PointerUnsupportedError):
        portal.open_pointer_sink(declined, start_timeout=1.0)
    assert declined.dialogs == [KEYBOARD_AND_POINTER]

    restarted = _GnomePortalSession(store)
    with pytest.raises(PointerUnsupportedError):
        portal.open_pointer_sink(restarted, start_timeout=1.0)
    assert restarted.dialogs == []


# --------------------------------------------------------------------------- #
# The keyboard path is unchanged
# --------------------------------------------------------------------------- #
def test_a_token_saved_by_an_earlier_release_is_offered_for_the_keyboard(
    sandboxed_token,
) -> None:
    (sandboxed_token / portal.TOKEN_FILENAME).write_text("old-token", encoding="utf-8")
    session = _FakePortalSession()
    session.ensure_started(1.0)
    assert session.select_options()["restore_token"] == ("s", "old-token")


def test_the_token_file_still_holds_the_token_alone(sandboxed_token) -> None:
    portal.write_token("only-the-token", KEYBOARD_AND_POINTER)
    raw = (sandboxed_token / portal.TOKEN_FILENAME).read_text(encoding="utf-8")
    assert raw == "only-the-token"
    record = (sandboxed_token / portal.TOKEN_DEVICES_FILENAME).read_text(encoding="utf-8")
    assert "only-the-token" not in record


def test_turning_the_pointer_off_keeps_the_token_and_its_record() -> None:
    store: dict[str, int] = {}
    pointer_run = _GnomePortalSession(store)
    portal.open_pointer_sink(pointer_run, start_timeout=1.0)

    keyboard_run = _GnomePortalSession(store)
    keyboard_run.ensure_started(1.0)

    assert "restore_token" in keyboard_run.select_options()
    assert keyboard_run.dialogs == []
    assert keyboard_run.pointer_granted is False, "not requested, so not used"
    assert portal.token_devices(portal.read_token()) == KEYBOARD_AND_POINTER


# --------------------------------------------------------------------------- #
# The record itself
# --------------------------------------------------------------------------- #
def test_a_record_for_another_token_counts_as_keyboard_only(sandboxed_token) -> None:
    """An older YazSes rewrites the single-use token and leaves the sidecar behind."""
    portal.write_token("with-pointer", KEYBOARD_AND_POINTER)
    (sandboxed_token / portal.TOKEN_FILENAME).write_text("rewritten", encoding="utf-8")
    assert portal.token_devices("rewritten") == KEYBOARD


@pytest.mark.parametrize("junk", ["", "3", "x y", "3 not-the-digest", "a b c"])
def test_an_unreadable_record_counts_as_keyboard_only(sandboxed_token, junk: str) -> None:
    portal.write_token("tok", KEYBOARD_AND_POINTER)
    (sandboxed_token / portal.TOKEN_DEVICES_FILENAME).write_text(junk, encoding="utf-8")
    assert portal.token_devices("tok") == KEYBOARD


def test_a_late_pointer_consumer_does_not_inherit_a_stale_token(sandboxed_token) -> None:
    portal.write_token("keyboard-token")
    session = _FakePortalSession()
    portal.DeferredPortalPointerSink(session)
    session.ensure_started(1.0)
    assert "restore_token" not in _selects(session)[0]


# --------------------------------------------------------------------------- #
# The explanation follows the dialog
# --------------------------------------------------------------------------- #
class _RunNow:
    def __init__(self, target=None, **_kw):
        self._target = target

    def start(self):
        if self._target is not None:
            self._target()


def _toasts_at_start(monkeypatch, *, wants_pointer: bool) -> list[tuple]:
    toasts: list[tuple] = []
    monkeypatch.setattr("yazses.core.daemon.threading.Thread", _RunNow)
    monkeypatch.setattr(notify_mod, "notify", lambda *a, **kw: toasts.append(a))
    backend = types.SimpleNamespace(warm=lambda: True, wants_pointer=wants_pointer)
    Daemon._warm_portal_session(types.SimpleNamespace(_injector=backend))
    return toasts


def test_the_widening_dialog_is_explained_with_the_pointer_wording(monkeypatch) -> None:
    portal.write_token("keyboard-token")
    toasts = _toasts_at_start(monkeypatch, wants_pointer=True)
    assert len(toasts) == 1
    assert "pointer" in toasts[0][1] and "no mouse" not in toasts[0][1]


@pytest.mark.parametrize(
    ("devices", "wants_pointer"),
    [(KEYBOARD, False), (KEYBOARD_AND_POINTER, True), (KEYBOARD_AND_POINTER, False)],
)
def test_no_explanation_when_the_token_covers_the_request(
    monkeypatch, devices: int, wants_pointer: bool
) -> None:
    portal.write_token("saved", devices)
    assert _toasts_at_start(monkeypatch, wants_pointer=wants_pointer) == []
