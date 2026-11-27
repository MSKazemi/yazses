"""A dictation's budget bounds the whole portal negotiation, not only `Start`.

`_ready` asks for the session within `HOT_PATH_TIMEOUT_S`, but `CreateSession` and
`SelectDevices` waited `REQUEST_TIMEOUT_S` regardless. A desktop portal that stopped
answering `CreateSession` therefore froze each dictation for 30 s before the
clipboard fallback ran, on a path documented as never waiting that long.
"""
from __future__ import annotations

import contextlib

import pytest

from tests.test_pointer_portal import _FakePortalSession
from yazses.inject import portal


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


class _BudgetSession(_FakePortalSession):
    """Records each request's timeout and lets each one take ``takes`` seconds."""

    def __init__(self, clock: _Clock, takes: float = 0.0) -> None:
        super().__init__()
        self.clock = clock
        self.takes = takes
        self.budgets: dict[str, float] = {}

    def _call_with_response(self, member, signature, body, timeout):
        self.budgets[member] = timeout
        self.clock.now += self.takes
        return super()._call_with_response(member, signature, body, timeout)


@pytest.fixture(autouse=True)
def sandboxed_token(tmp_path, monkeypatch):
    monkeypatch.setenv("YAZSES_DATA_DIR", str(tmp_path))


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(portal.time, "monotonic", fake.monotonic)
    return fake


def test_no_request_in_a_dictation_waits_longer_than_the_dictation_budget(clock):
    session = _BudgetSession(clock)
    session.ensure_started(portal.HOT_PATH_TIMEOUT_S)
    assert set(session.budgets) == {"CreateSession", "SelectDevices", "Start"}
    assert max(session.budgets.values()) <= portal.HOT_PATH_TIMEOUT_S


def test_the_budget_is_shared_by_the_three_requests(clock):
    session = _BudgetSession(clock, takes=2.0)
    session.ensure_started(5.0)
    assert session.budgets == {"CreateSession": 5.0, "SelectDevices": 3.0, "Start": 1.0}


def test_a_spent_budget_stops_the_negotiation(clock):
    session = _BudgetSession(clock, takes=6.0)
    with pytest.raises(portal.PortalUnavailable, match="did not answer"):
        session.ensure_started(5.0)
    assert list(session.budgets) == ["CreateSession"]
    assert session.started is False


def test_warm_up_keeps_its_long_dialog_budget(clock):
    session = _BudgetSession(clock)
    session.ensure_started(portal.START_TIMEOUT_S)
    assert session.budgets["CreateSession"] == portal.REQUEST_TIMEOUT_S
    assert session.budgets["SelectDevices"] == portal.REQUEST_TIMEOUT_S
    assert session.budgets["Start"] == portal.START_TIMEOUT_S


def test_the_method_call_itself_is_bounded_too(monkeypatch):
    """The reply to the call, before the Response signal, honours the budget."""
    pytest.importorskip("jeepney")
    seen: list[float] = []

    class _Stop(Exception):
        pass

    class _Proxy:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def AddMatch(self, rule) -> None:
            pass

        def RemoveMatch(self, rule) -> None:
            pass

    class _Conn:
        unique_name = ":1.1"

        def filter(self, rule):
            return contextlib.nullcontext(object())

        def send_and_get_reply(self, msg, timeout):
            seen.append(timeout)
            raise _Stop

    monkeypatch.setattr("jeepney.io.blocking.Proxy", _Proxy)
    session = portal._PortalSession()
    session._conn = _Conn()
    with pytest.raises(_Stop):
        session._call_with_response("CreateSession", "a{sv}", ({},), 2.0)
    assert seen == [2.0]
