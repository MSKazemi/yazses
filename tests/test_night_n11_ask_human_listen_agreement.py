"""The MCP client and the daemon must agree on how long `ask_human` listens.

The daemon reads the listening time as ``float(params.get("timeout_s") or 30.0)``
(`core/daemon.py`, `_handle_ask_human`) and `AskHumanService.ask` clamps it to
1..120 s. The MCP tool used to send the caller's value unchanged and work out its
own IPC wait from it, so ``timeout_s=0`` made the daemon listen for 30 s while the
client gave up about 20 s after the question was spoken -- the question was asked,
charged to the hour, and the answer was lost. NaN and infinity were put on the
wire as the non-standard JSON tokens ``NaN`` / ``Infinity``.

Pure and offline: a fake IPC client records what would be sent, and the daemon's
side is the real `AskHumanService` with a recording listener.
"""

from __future__ import annotations

import json
import math

import pytest

from yazses.config import Config
from yazses.mcp.ask import AskHumanService
from yazses.mcp.server import build_tools


class _FakePlatform:
    def __init__(self, client) -> None:
        self._client = client
        self.paths = type("P", (), {"ipc_socket": "unused"})()

    def ipc_client_factory(self, _path):
        return self._client


def _ask_tool():
    cfg = Config()
    object.__setattr__(cfg.mcp, "ask_human", True)
    return [t for t in build_tools(cfg) if t.name == "ask_human"][0]


def _sent_params(monkeypatch, timeout_s) -> dict:
    seen: dict = {}

    class _Client:
        def call(self, method, **params):
            seen.update(params)
            return {"ok": True, "answer": "yes"}

    import yazses.platform as platform_mod

    monkeypatch.setattr(platform_mod, "get_platform", lambda: _FakePlatform(_Client()))
    assert _ask_tool().run(question="go?", timeout_s=timeout_s) == "yes"
    return seen


def _daemon_listen_s(sent_timeout_s) -> float:
    """What the daemon actually listens for, given the params it received."""
    heard: list[float] = []

    class _Speaker:
        def speak(self, _text: str) -> None:
            return None

    def _listener(wait: float) -> str:
        heard.append(wait)
        return "yes"

    service = AskHumanService(
        speaker=_Speaker(), listener=_listener, max_per_hour=100, enabled=True,
        is_holding=lambda: False, clock=lambda: 0.0,
    )
    # Mirrors the daemon's own parsing of the IPC params (`_handle_ask_human`).
    service.ask("go?", caller="mcp", timeout_s=float(sent_timeout_s or 30.0))
    return heard[0]


@pytest.mark.parametrize(
    "asked", [0, 0.0, 0.25, -3, 1, 45, 120, 500, float("nan"), float("inf")]
)
def test_the_client_waits_at_least_as_long_as_the_daemon_listens(monkeypatch, asked) -> None:
    sent = _sent_params(monkeypatch, asked)
    daemon_listens = _daemon_listen_s(sent["timeout_s"])
    # The 20 s margin is for transcription; it must not be spent on listening the
    # client did not count.
    assert sent["wait_s"] >= daemon_listens + 20.0, (asked, sent, daemon_listens)


def test_zero_means_the_default_on_both_sides(monkeypatch) -> None:
    sent = _sent_params(monkeypatch, 0)
    assert sent["timeout_s"] == 30.0
    assert _daemon_listen_s(sent["timeout_s"]) == 30.0


@pytest.mark.parametrize("asked", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_timeout_never_reaches_the_wire(monkeypatch, asked) -> None:
    sent = _sent_params(monkeypatch, asked)
    assert math.isfinite(sent["timeout_s"])
    assert math.isfinite(sent["wait_s"])
    # Strict JSON: what the IPC client serialises must not need NaN/Infinity tokens.
    json.dumps({"timeout_s": sent["timeout_s"], "wait_s": sent["wait_s"]}, allow_nan=False)


def test_an_ordinary_timeout_is_sent_unchanged(monkeypatch) -> None:
    sent = _sent_params(monkeypatch, 45)
    assert sent["timeout_s"] == 45


@pytest.mark.parametrize(
    "asked, listen",
    [(0, 30.0), (-1, 30.0), (0.25, 1.0), (1, 1.0), (60, 60.0), (121, 120.0),
     (float("inf"), 120.0), (float("nan"), 30.0), ("x", 30.0), (None, 30.0), (True, 30.0)],
)
def test_ask_human_listen_s(asked, listen) -> None:
    from yazses.mcp.server import ask_human_listen_s

    assert ask_human_listen_s(asked) == listen
