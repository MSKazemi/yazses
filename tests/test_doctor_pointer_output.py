"""`yazses doctor`'s "Pointer output" row says the real situation, not "unknown".

The row used to ask the platform for a ``pointer_capabilities()`` that no platform defines, so
it printed "unknown" on every machine for ever. It now reports (1) which backend would drive
the pointer on this session -- from the session type, the typing backend and the installed
packages -- and (2) whether the desktop's permission has been granted this *daemon session*,
read from the running daemon, or "daemon not running".

The contract held here beyond the wording: **doctor stays read-only.** The platform double
below raises on any pointer-related attribute, so a regression that built a pointer sink,
asked the portal, or called a pointer factory fails the run instead of quietly raising a
consent dialog on somebody's desktop. Nothing in this file touches a real display, session
bus or pointer.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from yazses.config import Config
from yazses.handsfree.observability import HandsFreeFacts
from yazses.handsfree.probe import (
    PointerEnvironment,
    pointer_route_facts,
    read_pointer_environment,
)
from yazses.system.doctor import _handsfree_checks, _headpointer_daemon_view

WAYLAND_PORTAL = PointerEnvironment("wayland", "portal", None, False)
WAYLAND_YDOTOOL = PointerEnvironment("wayland", "ydotool", None, False)
WAYLAND_UNSURE = PointerEnvironment("wayland", None, None, False)
X11 = PointerEnvironment("x11", None, True, True)
HEADLESS = PointerEnvironment("headless", None, None, False)

NOT_RUNNING = (False, None)


class _Platform:
    """Answers about paths only; raises on anything that would touch a pointer."""

    name = "linux"

    class paths:
        data_dir = Path("/nonexistent/yazses-data")

    def __getattr__(self, name):
        # `pointer_capabilities` is the optional, session-free seam doctor may ask about;
        # anything else pointer-shaped (`pointer_factory`) would open or build a sink.
        if "pointer" in name and name != "pointer_capabilities":
            raise AssertionError(f"doctor touched platform.{name}; it must stay read-only")
        raise AttributeError(name)


def _cfg() -> Config:
    cfg = Config()
    cfg.headpointer.enabled = True
    return cfg


def _row(env, daemon_view=NOT_RUNNING) -> tuple[str, str]:
    rows = _handsfree_checks(
        _cfg(), _Platform(), ("Camera", "OK", "ready"),
        unwired=frozenset(), pointer_env=env, daemon_view=daemon_view,
    )
    return {label: (status, detail) for label, status, detail in rows}["Pointer output"]


def _live(**kw) -> dict:
    base = {"ok": True, "active": True, "backend": "portal", "state": "tracking"}
    return {**base, **kw}


# ------------------------------------------------------------------ which backend


def test_x11_names_x11_and_needs_no_permission() -> None:
    status, detail = _row(X11)
    assert status == "OK"
    assert "x11" in detail and "no permission step" in detail


def test_wayland_with_portal_typing_names_the_portal() -> None:
    status, detail = _row(WAYLAND_PORTAL)
    assert "portal" in detail
    assert status == "SKIP"  # consent is not knowable without a daemon


def test_wayland_with_other_typing_says_none_and_how_to_fix_it() -> None:
    status, detail = _row(WAYLAND_YDOTOOL)
    assert status == "WARN"
    assert detail.startswith("none")
    assert "ydotool" in detail and 'backend = "portal"' in detail


def test_headless_says_none() -> None:
    status, detail = _row(HEADLESS)
    assert status == "WARN" and detail.startswith("none")


def test_the_row_never_says_unknown_for_a_known_session() -> None:
    for env in (X11, WAYLAND_PORTAL, WAYLAND_YDOTOOL, HEADLESS):
        _status, detail = _row(env)
        assert not detail.startswith("unknown"), detail


def test_an_unconfirmed_typing_backend_is_never_a_clean_ok() -> None:
    status, detail = _row(WAYLAND_UNSURE, daemon_view=(True, {"ok": True, "active": False,
                                                              "reason": "no shared camera"}))
    assert status == "SKIP", "a prediction that depends on an unseen fact must not read OK"
    assert "portal" in detail


# ------------------------------------------------------------------ consent this daemon session


def test_daemon_not_running_is_said_in_those_words() -> None:
    status, detail = _row(WAYLAND_PORTAL, NOT_RUNNING)
    assert status == "SKIP"
    assert "daemon not running" in detail
    assert "yazses start" in detail


@pytest.mark.parametrize(
    ("consent", "status", "needle"),
    [
        ("granted", "OK", "permission granted this daemon session"),
        ("pending_consent", "WARN", "permission pending"),
        ("denied", "WARN", "permission was not given"),
        ("unavailable", "WARN", "offers no pointer"),
        ("unknown", "SKIP", "permission"),
    ],
)
def test_the_live_daemon_decides_the_permission_wording(consent, status, needle) -> None:
    live = _live(consent=consent, consent_reason="because")
    got_status, detail = _row(WAYLAND_PORTAL, (True, live))
    assert got_status == status, detail
    assert needle in detail


def test_pending_tells_the_user_what_to_do_and_that_no_restart_is_needed() -> None:
    rows = _handsfree_checks(
        _cfg(), _Platform(), ("Camera", "OK", "ready"), unwired=frozenset(),
        pointer_env=WAYLAND_PORTAL, daemon_view=(True, _live(consent="pending_consent")),
    )
    detail = {label: d for label, _s, d in rows}["Pointer output"]
    assert "dialog" in detail and "no restart" in detail


def test_denied_tells_the_user_how_to_be_asked_again() -> None:
    _status, detail = _row(WAYLAND_PORTAL, (True, _live(consent="denied")))
    assert "yazses restart" in detail


def test_the_daemons_own_backend_beats_the_prediction() -> None:
    """Doctor guessed portal; the daemon says it is on x11 -- the daemon is right."""
    live = _live(backend="x11", consent="")
    status, detail = _row(WAYLAND_PORTAL, (True, live))
    assert status == "OK"
    assert detail.startswith("x11")


def test_a_running_daemon_with_no_active_head_pointer_is_distinguished_from_not_running() -> None:
    live = {"ok": True, "active": False, "reason": "no shared camera source"}
    _status, detail = _row(WAYLAND_PORTAL, (True, live))
    assert "daemon not running" not in detail
    assert "Head-Pointer is not" in detail
    assert "no shared camera source" in detail


def test_a_running_daemon_that_did_not_answer_is_not_called_not_running() -> None:
    _status, detail = _row(WAYLAND_PORTAL, (True, None))
    assert "daemon not running" not in detail


def test_x11_never_mentions_a_daemon_even_when_it_is_down() -> None:
    _status, detail = _row(X11, NOT_RUNNING)
    assert "daemon" not in detail


# ------------------------------------------------------------------ pure combiner


def test_a_backend_a_platform_already_named_is_left_alone() -> None:
    facts = HandsFreeFacts(features_requested=("headpointer",), pointer_backend="sendinput")
    assert pointer_route_facts(facts, X11, daemon_running=False) is facts


def test_the_platforms_own_reason_survives_the_prediction() -> None:
    facts = HandsFreeFacts(
        features_requested=("headpointer",), pointer_reason="the platform could not report"
    )
    out = pointer_route_facts(facts, HEADLESS, daemon_running=False)
    assert "could not report" in out.pointer_reason


def test_a_failed_live_reply_falls_back_to_the_prediction() -> None:
    facts = HandsFreeFacts(features_requested=("headpointer",))
    out = pointer_route_facts(facts, X11, daemon_running=True, live={"ok": False})
    assert out.pointer_backend == "x11"


# ------------------------------------------------------------------ the environment reader


def test_the_reader_maps_the_session_like_the_factory_does() -> None:
    def read(environ, fixed=None):
        return read_pointer_environment(
            _cfg(), environ=environ, fixed_session=lambda: fixed,
            typing_backend=lambda: "portal", xlib_available=lambda: True,
        )

    assert read({"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "w0"}).session_type == "wayland"
    # Only XDG_SESSION_TYPE=wayland refuses XTEST; anything else with a DISPLAY is X11.
    assert read({"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}).session_type == "x11"
    assert read({"DISPLAY": ":0"}).session_type == "x11"
    assert read({}).session_type == "headless"
    assert read({"XDG_SESSION_TYPE": "wayland"}, fixed="windows").session_type == "windows"


def test_the_reader_only_asks_the_typing_backend_on_wayland() -> None:
    asked = []

    def typing():
        asked.append(1)
        return "portal"

    read_pointer_environment(
        _cfg(), environ={"DISPLAY": ":0"}, fixed_session=lambda: None,
        typing_backend=typing, xlib_available=lambda: True,
    )
    assert asked == []
    env = read_pointer_environment(
        _cfg(), environ={"XDG_SESSION_TYPE": "wayland"}, fixed_session=lambda: None,
        typing_backend=typing, xlib_available=lambda: True,
    )
    assert asked == [1] and env.typing_backend == "portal"


def test_a_probe_that_raises_is_unknown_not_a_crash() -> None:
    def boom():
        raise OSError("no bus")

    env = read_pointer_environment(
        _cfg(), environ={"XDG_SESSION_TYPE": "wayland"}, fixed_session=boom,
        typing_backend=boom, xlib_available=boom,
    )
    assert env.typing_backend is None


# ------------------------------------------------------------------ the daemon view


class _Lifecycle:
    def __init__(self, running: bool) -> None:
        self._running = running

    def is_running(self) -> bool:
        return self._running


class _Client:
    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self.reply, self.error, self.calls = reply, error, []

    def call(self, method, **params):
        self.calls.append((method, params))
        if self.error:
            raise self.error
        return self.reply


def _platform(running: bool, client: _Client):
    class P:
        lifecycle = _Lifecycle(running)

        class paths:
            ipc_socket = Path("/nonexistent/sock")

        @staticmethod
        def ipc_client_factory(_sock):
            return client

    return P()


def test_the_daemon_view_makes_no_call_when_the_daemon_is_not_running() -> None:
    client = _Client()
    assert _headpointer_daemon_view(_platform(False, client)) == (False, None)
    assert client.calls == []


def test_the_daemon_view_makes_exactly_one_read_only_status_call() -> None:
    client = _Client(reply={"ok": True, "active": True})
    running, live = _headpointer_daemon_view(_platform(True, client))
    assert running is True and live == {"ok": True, "active": True}
    assert client.calls == [("headpointer", {"action": "status"})]


def test_an_ipc_error_is_running_with_no_answer() -> None:
    client = _Client(error=OSError("socket not ready"))
    assert _headpointer_daemon_view(_platform(True, client)) == (True, None)


def test_a_lifecycle_that_raises_is_not_running() -> None:
    class P:
        class lifecycle:
            @staticmethod
            def is_running():
                raise RuntimeError("pidfile unreadable")

    assert _headpointer_daemon_view(P()) == (False, None)


# ------------------------------------------------------------------ read-only


def test_building_the_row_never_touches_a_pointer_factory() -> None:
    """The platform double raises on any `*pointer*` attribute; reaching it fails the run."""
    for env in (X11, WAYLAND_PORTAL, WAYLAND_YDOTOOL, HEADLESS):
        _row(env)  # would raise AssertionError if doctor read platform.pointer_factory


def test_with_the_head_pointer_off_nothing_about_the_pointer_is_read(monkeypatch) -> None:
    """A face-switch-only install pays nothing: no env read, no daemon call."""
    from yazses.handsfree import probe as probe_mod
    from yazses.system import doctor as doctor_mod

    def explode(*_a, **_k):
        raise AssertionError("the pointer was probed without a head pointer being enabled")

    monkeypatch.setattr(probe_mod, "read_pointer_environment", explode)
    monkeypatch.setattr(doctor_mod, "_headpointer_daemon_view", explode)
    cfg = Config()
    cfg.facegesture.enabled = True

    rows = _handsfree_checks(cfg, _Platform(), ("Camera", "OK", "ready"), unwired=frozenset())

    assert "Pointer output" not in {label for label, _s, _d in rows}
