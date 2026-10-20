"""The Head-Pointer on native Wayland: reach the daemon's live portal session (ADR-v2-146).

`LinuxInjector` types through the RemoteDesktop portal when that is the backend chosen, and
rule 6 of the ADR says the pointer must extend **that** session -- one dialog, one restore
token, one grant. These tests hold the wiring that makes it so, and the three ways it can
fail honestly:

* **The pointer rides the injector's own session.** `Platform.pointer_factory` asks the live
  injector, so the sink and the keyboard share one `_PortalSession` (one `CreateSession`).
* **Building the pointer raises no dialog and blocks nothing.** The daemon builds its
  features before the hotkey is live; the consent dialog belongs to the `warm()` thread. The
  deferred sink registers interest and sends nothing until the session exists and the
  compositor granted POINTER.
* **Failure leaves nothing half-open.** A cancelled dialog is reported as such, rolls the
  session back (the keyboard bug fixed in #403), and a sink that is waiting never sends.
* **X11 is untouched, and a non-portal injector is a precise refusal**, not a rival client.

The D-Bus layer is the injected fake from `tests/test_pointer_portal.py`: the negotiation under
test is the shipped code, CI needs no compositor, no bus and no dialog. As there, what is
asserted is "the right call, in the right order, never before consent" -- never "the pointer
moved", which only the live smoke can show.
"""
from __future__ import annotations

import types

import pytest

from tests.pointer_contract import PointerSinkContract
from tests.pointer_fake import PointerAction
from tests.test_pointer_portal import (
    KEYBOARD_AND_POINTER,
    _FakePortalSession,
)
from yazses.config import Config
from yazses.headpointer.runtime import build_headpointer
from yazses.inject import portal
from yazses.platform import linux as linux_platform
from yazses.platform.linux.injector import LinuxInjector
from yazses.pointer.base import (
    PointerBackendError,
    PointerSink,
    PointerUnsupportedError,
)


@pytest.fixture(autouse=True)
def sandboxed_token(tmp_path, monkeypatch):
    """No test here reads or writes the developer's own restore token."""
    monkeypatch.setenv("YAZSES_DATA_DIR", str(tmp_path))
    return tmp_path


def _linux_injector(primary: object) -> LinuxInjector:
    """A real `LinuxInjector` around *primary*, without selecting a backend from the host."""
    injector = object.__new__(LinuxInjector)
    injector._primary = primary  # type: ignore[assignment]
    injector._fallback = None
    return injector


def _portal_linux_injector(session: _FakePortalSession) -> LinuxInjector:
    return _linux_injector(portal.PortalInjector(session=session))


class _Ydotool:
    """Stands in for a non-portal primary. Its class name is what the refusal quotes."""

    def inject(self, text: str) -> None:  # pragma: no cover - never called
        raise AssertionError("not typing in this test")


_Ydotool.__name__ = "YdotoolInjector"


# --------------------------------------------------------------------------- #
# The deferred sink, against the shared contract
# --------------------------------------------------------------------------- #
class TestDeferredPortalPointerSink(PointerSinkContract):
    """Once its session is up, the deferred sink is a `PointerSink` like any other."""

    def setup_method(self) -> None:
        self._sessions: dict[int, _FakePortalSession] = {}

    def make_sink(self) -> portal.DeferredPortalPointerSink:
        session = _FakePortalSession()
        sink = portal.DeferredPortalPointerSink(session)
        session.ensure_started(1.0)  # what the daemon's warm() thread does
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
# Building it asks nothing and sends nothing
# --------------------------------------------------------------------------- #
def test_building_the_sink_makes_no_portal_call_and_no_connection() -> None:
    session = _FakePortalSession()
    sink = portal.DeferredPortalPointerSink(session)

    assert session.calls == []
    assert session.connections == 0
    assert session.started is False
    assert session.wants_pointer is True
    assert sink.capabilities().backend == "portal"


def test_a_sink_whose_dialog_is_still_open_fails_loudly_and_sends_nothing() -> None:
    """Waiting is an error with a reason, never a dropped event and never an ask."""
    session = _FakePortalSession()
    sink = portal.DeferredPortalPointerSink(session)

    with pytest.raises(PointerBackendError, match="waiting for the desktop"):
        sink.move_relative(1.0, 1.0)
    with pytest.raises(PointerBackendError, match="waiting"):
        sink.click()

    assert session.calls == [], "a pending sink must not negotiate -- warm() owns the dialog"
    assert session.notified == []


def test_the_warm_up_the_daemon_runs_gives_dictation_and_pointer_one_session() -> None:
    """The point of the whole change: one `CreateSession`, POINTER in the one mask."""
    session = _FakePortalSession()
    injector = portal.PortalInjector(session=session)
    sink = injector.deferred_pointer_sink()
    assert injector.wants_pointer is True

    assert injector.warm() is True  # the daemon's warm() thread

    injector.inject("a")
    sink.move_relative(2.0, 3.0)

    assert session.select_options()["types"] == ("u", KEYBOARD_AND_POINTER)
    assert session.members == ["CreateSession", "SelectDevices", "Start"]
    assert session.connections == 1
    assert [member for member, _, _ in session.notified] == [
        "NotifyKeyboardKeysym",
        "NotifyKeyboardKeysym",
        "NotifyPointerMotion",
    ]


def test_a_dictation_only_injector_does_not_want_the_pointer() -> None:
    """ADR-v2-146 rule 7: nothing registers a consumer unless a pointer feature asked."""
    session = _FakePortalSession()
    injector = portal.PortalInjector(session=session)
    assert injector.wants_pointer is False
    injector.warm()
    assert session.select_options()["types"] == ("u", portal.DEVICE_KEYBOARD)


# --------------------------------------------------------------------------- #
# Refusal leaves nothing half-open
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("refused", ["SelectDevices", "Start"])
def test_a_cancelled_dialog_is_reported_and_leaves_no_half_open_session(refused: str) -> None:
    session = _FakePortalSession(refuse=refused)
    injector = portal.PortalInjector(session=session)
    sink = injector.deferred_pointer_sink()

    assert injector.warm() is False  # the user pressed Cancel

    assert session.started is False
    assert session._session_handle == ""
    assert session._conn is None, "the connection of a refused negotiation must be closed"
    with pytest.raises(PointerBackendError, match="permission was not given"):
        sink.move_relative(1.0, 1.0)
    assert session.notified == []

    # A retry negotiates for real (the session is not stuck on a dead handle) and the
    # same sink then works: the registration survived the refusal.
    session.refuse = ""
    session.calls.clear()
    assert injector.warm() is True
    assert session.members == ["CreateSession", "SelectDevices", "Start"]
    sink.move_relative(1.0, 0.0)
    assert session.actions == [PointerAction.move_relative(1.0, 0.0)]


def test_a_keyboard_only_grant_is_unsupported_not_silent() -> None:
    session = _FakePortalSession(granted=portal.DEVICE_KEYBOARD)
    sink = portal.DeferredPortalPointerSink(session)
    session.ensure_started(1.0)

    with pytest.raises(PointerUnsupportedError, match="did not grant"):
        sink.move_relative(1.0, 1.0)
    assert session.notified == []


def test_registering_on_a_keyboard_only_session_refuses_at_build_time() -> None:
    """No second dialog mid-sentence: said immediately, so `status` shows it at once."""
    session = _FakePortalSession()
    session.ensure_started(1.0)

    with pytest.raises(PointerBackendError, match="restart"):
        portal.DeferredPortalPointerSink(session)

    assert session.members.count("Start") == 1
    assert session.wants_pointer is False


def test_close_hands_the_consumer_back_once_and_leaves_dictation_open() -> None:
    session = _FakePortalSession()
    injector = portal.PortalInjector(session=session)
    sink = injector.deferred_pointer_sink()
    injector.warm()
    sink.move_relative(1.0, 0.0)

    sink.close()
    sink.close()  # idempotent

    assert session.wants_pointer is False
    assert session.started is True, "closing the pointer must not end typing"
    with pytest.raises(PointerBackendError, match="closed"):
        sink.move_relative(1.0, 0.0)
    injector.inject("a")
    assert session.notified[-1][0] == "NotifyKeyboardKeysym"


def test_closing_a_sink_that_never_opened_still_releases_its_registration() -> None:
    session = _FakePortalSession()
    sink = portal.DeferredPortalPointerSink(session)
    sink.close()
    sink.close()
    assert session.wants_pointer is False
    assert session.calls == []


def test_a_session_re_negotiated_after_a_close_serves_the_same_sink() -> None:
    """The consumer count keeps POINTER in the next mask; no second request, no new dialog."""
    session = _FakePortalSession()
    sink = portal.DeferredPortalPointerSink(session)
    session.ensure_started(1.0)
    sink.move_relative(1.0, 0.0)

    session.close()  # e.g. shutdown path / explicit close
    with pytest.raises(PointerBackendError):
        sink.move_relative(1.0, 0.0)

    session.ensure_started(1.0)  # dictation re-opens it
    sink.move_relative(2.0, 0.0)

    assert session.members.count("SelectDevices") == 2
    selects = [body[-1] for m, _, body in session.calls if m == "SelectDevices"]
    assert all(dict(s)["types"] == ("u", KEYBOARD_AND_POINTER) for s in selects)
    assert session.actions[-1] == PointerAction.move_relative(2.0, 0.0)


# --------------------------------------------------------------------------- #
# The idle reaper must not end a pointer that is merely still
# --------------------------------------------------------------------------- #
def _reapable(session: _FakePortalSession) -> None:
    """A session that dictation used long ago and that holds a restore token."""
    portal.write_token("saved")
    session.ensure_started(1.0)
    session.touch()


def test_the_idle_reaper_leaves_a_session_a_pointer_consumer_holds() -> None:
    """Head-Pointer sits still while the user reads; `portal_idle_release_s` is 60 by default.

    Without this the session closed a minute after the last word typed, the grant went with
    it, and the pointer faulted with no way back short of another dialog.
    """
    session = _FakePortalSession()
    portal.DeferredPortalPointerSink(session)
    _reapable(session)

    assert session.release_if_idle(60, now=session._last_used + 3600) is False
    assert session.started is True


def test_the_idle_reaper_still_closes_a_keyboard_only_session() -> None:
    """Control for the test above: the guard is the consumer, not a disabled reaper."""
    session = _FakePortalSession()
    _reapable(session)

    assert session.release_if_idle(60, now=session._last_used + 3600) is True
    assert session.started is False


# --------------------------------------------------------------------------- #
# LinuxInjector: the pointer comes from the backend actually chosen
# --------------------------------------------------------------------------- #
def test_a_portal_injector_yields_a_sink_on_its_own_session() -> None:
    session = _FakePortalSession()
    injector = _portal_linux_injector(session)

    sink = injector.pointer_sink()

    assert isinstance(sink, portal.DeferredPortalPointerSink)
    assert session.wants_pointer is True
    assert session.calls == [], "asking for the sink must not negotiate"


def test_a_non_portal_injector_is_a_precise_refusal_not_a_second_client() -> None:
    injector = _linux_injector(_Ydotool())

    with pytest.raises(PointerUnsupportedError) as caught:
        injector.pointer_sink()

    message = str(caught.value)
    assert "YdotoolInjector" in message, "it must name what is actually typing"
    assert 'backend = "portal"' in message, "and the one setting that changes it"


# --------------------------------------------------------------------------- #
# The Linux platform factory
# --------------------------------------------------------------------------- #
def test_the_wayland_factory_asks_the_live_injector(monkeypatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    opened: list[int] = []
    monkeypatch.setattr(linux_platform, "build_pointer_sink", lambda: opened.append(1))
    session = _FakePortalSession()

    sink = linux_platform._pointer_factory(_portal_linux_injector(session))

    assert isinstance(sink, portal.DeferredPortalPointerSink)
    assert opened == [], "XTEST must never be touched on a native Wayland session"
    assert session.connections == 0


def test_the_wayland_factory_without_an_injector_is_unsupported(monkeypatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    with pytest.raises(PointerUnsupportedError, match="Wayland"):
        linux_platform._pointer_factory(None)


def test_x11_never_consults_the_injector(monkeypatch) -> None:
    """The X11 path is byte-identical: same builder, injector not even looked at."""
    sentinel = object()
    monkeypatch.setattr(linux_platform, "build_pointer_sink", lambda: sentinel)

    class Exploding:
        def pointer_sink(self):  # pragma: no cover - must not be reached
            raise AssertionError("the X11 path must not ask the injector")

    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert linux_platform._pointer_factory(Exploding()) is sentinel
    monkeypatch.delenv("XDG_SESSION_TYPE")
    assert linux_platform._pointer_factory(Exploding()) is sentinel


def test_the_bundle_routes_the_daemons_injector_to_the_pointer(monkeypatch) -> None:
    """End to end through `build_platform()`: the injector the daemon builds is the one asked."""
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    session = _FakePortalSession()
    built: list[LinuxInjector] = []

    def make() -> LinuxInjector:
        built.append(_portal_linux_injector(session))
        return built[-1]

    monkeypatch.setattr("yazses.platform.linux.injector.LinuxInjector", make)
    platform = linux_platform.build_platform()
    assert platform.pointer_factory is not None

    # Before any injector exists there is nothing to extend.
    with pytest.raises(PointerUnsupportedError, match="no live injector"):
        platform.pointer_factory()

    injector = platform.injector_factory()
    sink = platform.pointer_factory()

    assert injector is built[0]
    assert isinstance(sink, portal.DeferredPortalPointerSink)
    assert injector._primary.wants_pointer is True  # type: ignore[attr-defined]


def test_the_bundle_does_not_keep_an_injector_alive(monkeypatch) -> None:
    import gc

    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(
        "yazses.platform.linux.injector.LinuxInjector",
        lambda: _portal_linux_injector(_FakePortalSession()),
    )
    platform = linux_platform.build_platform()
    platform.injector_factory()
    gc.collect()

    with pytest.raises(PointerUnsupportedError, match="no live injector"):
        platform.pointer_factory()


# --------------------------------------------------------------------------- #
# The Head-Pointer on top: honest at build time, nothing opened
# --------------------------------------------------------------------------- #
def _enabled() -> object:
    cfg = Config().headpointer
    cfg.enabled = True
    return cfg


class _Perception:
    def consumer(self, name: str):
        return types.SimpleNamespace(start=lambda: None, stop=lambda: None, latest=lambda: None)


def test_headpointer_builds_on_wayland_without_raising_a_dialog(monkeypatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    session = _FakePortalSession()
    injector = _portal_linux_injector(session)

    runtime = build_headpointer(
        _enabled(),
        perception=_Perception(),
        pointer_factory=lambda: linux_platform._pointer_factory(injector),
        thread=False,
    )

    assert runtime.active, runtime.reason
    assert session.calls == [], "building the Head-Pointer must not touch the portal"
    assert session.notified == []
    runtime.stop()
    assert session.wants_pointer is False, "stopping hands the registration back"


def test_headpointer_on_a_ydotool_only_wayland_says_why_in_status(monkeypatch) -> None:
    """The reason `yazses headpointer status` prints survives its 200-character bound."""
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    injector = _linux_injector(_Ydotool())

    runtime = build_headpointer(
        _enabled(),
        perception=_Perception(),
        pointer_factory=lambda: linux_platform._pointer_factory(injector),
        thread=False,
    )

    assert not runtime.active
    reason = runtime.command("status")["reason"]
    assert isinstance(reason, str)
    assert "YdotoolInjector" in reason
    assert 'backend = "portal"' in reason, reason


def test_a_pointer_registration_failure_is_a_reason_not_a_crash(monkeypatch) -> None:
    """Keyboard-only session already running: said at once, no half-open anything."""
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    session = _FakePortalSession()
    session.ensure_started(1.0)
    injector = _portal_linux_injector(session)

    runtime = build_headpointer(
        _enabled(),
        perception=_Perception(),
        pointer_factory=lambda: linux_platform._pointer_factory(injector),
        thread=False,
    )

    assert not runtime.active
    assert "restart" in runtime.reason
    assert session.members.count("Start") == 1


# --------------------------------------------------------------------------- #
# The daemon's consent explanation follows the request
# --------------------------------------------------------------------------- #
class _RunNow:
    """A Thread stand-in that runs the target inline, so ordering is assertable."""

    def __init__(self, target=None, **_kw):
        self._target = target

    def start(self):
        if self._target is not None:
            self._target()


@pytest.mark.parametrize("pointer", [False, True])
def test_the_consent_toast_describes_the_request_actually_made(monkeypatch, pointer) -> None:
    from yazses.core.daemon import Daemon
    from yazses.system import notify as notify_mod

    toasts: list[tuple] = []
    monkeypatch.setattr("yazses.core.daemon.threading.Thread", _RunNow)
    monkeypatch.setattr(notify_mod, "notify", lambda title, body, **kw: toasts.append((title, body)))
    session = _FakePortalSession()
    injector = portal.PortalInjector(session=session)
    if pointer:
        injector.deferred_pointer_sink()
    daemon = types.SimpleNamespace(_injector=_linux_injector(injector))

    Daemon._warm_portal_session(daemon)

    assert len(toasts) == 1
    title, body = toasts[0]
    if pointer:
        assert "move the pointer" in title
        assert "keyboard and the pointer" in body
    else:
        assert "no mouse" in body, "a dictation-only request keeps its keyboard-only copy"
