"""`yazses send-to <client> [TEXT]` (ADR-031): refusals first, and the text never echoed.

With TEXT the hand-off runs in the CLI's own process (the text never travels to the
daemon); without it the daemon's `send_to` IPC method picks the staged buffer or the
last burst. Both paths are covered with the opener and the platform faked, so nothing
is launched and no daemon is needed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.cli import app
from yazses.ipc.client import IpcCallError
from yazses.sendto import handoff
from yazses.sendto.targets import CLAUDE_MAX_CHARS

runner = CliRunner()

PROMPT_MARKER = "PROMPT_MARKER-PROMPT-zebra-7731"


class _Opener:
    def __init__(self, result: bool = True):
        self.calls: list[str] = []
        self.result = result

    def __call__(self, url: str) -> bool:
        self.calls.append(url)
        return self.result


def _platform(monkeypatch, tmp_path, config: str, *, running: bool = False, client=None):
    """Point the CLI at a throwaway config and a fake daemon lifecycle."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(config, encoding="utf-8")
    platform = SimpleNamespace(
        paths=SimpleNamespace(config_file=cfg_file, ipc_socket=tmp_path / "ipc.sock"),
        lifecycle=SimpleNamespace(is_running=lambda: running),
        ipc_client_factory=lambda _path: client,
    )
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    return platform


ON = "[sendto]\nenabled = true\n"


@pytest.fixture
def opener(monkeypatch):
    fake = _Opener()
    monkeypatch.setattr(handoff, "default_opener", fake)
    return fake


def test_an_unknown_app_is_refused_before_anything_else(monkeypatch, tmp_path, opener):
    _platform(monkeypatch, tmp_path, ON)
    result = runner.invoke(app, ["send-to", "chatgpt", "hello"])
    assert result.exit_code == 2
    assert "claude, claude-code, codex" in result.output
    assert opener.calls == []


def test_it_refuses_while_the_feature_is_off(monkeypatch, tmp_path, opener):
    _platform(monkeypatch, tmp_path, "")
    result = runner.invoke(app, ["send-to", "claude", PROMPT_MARKER])
    assert result.exit_code == 1
    assert "Send to is off" in result.output
    assert opener.calls == []


def test_explicit_text_is_handed_off_and_never_echoed(monkeypatch, tmp_path, opener):
    _platform(monkeypatch, tmp_path, ON)
    result = runner.invoke(app, ["send-to", "claude", PROMPT_MARKER])
    assert result.exit_code == 0, result.output
    assert opener.calls == [f"claude://claude.ai/new?q={PROMPT_MARKER}"]
    assert PROMPT_MARKER not in result.output
    assert f"Opened Claude with {len(PROMPT_MARKER)} characters" in result.output
    assert "press Enter" in result.output


def test_explicit_text_does_not_need_the_daemon(monkeypatch, tmp_path, opener):
    """No client is configured on the fake platform: an IPC call would raise."""
    _platform(monkeypatch, tmp_path, ON, running=False, client=None)
    result = runner.invoke(app, ["send-to", "codex", "hi"])
    assert result.exit_code == 0, result.output
    assert opener.calls == ["codex://new?prompt=hi"]


def test_text_over_the_limit_is_refused_with_the_numbers(monkeypatch, tmp_path, opener):
    _platform(monkeypatch, tmp_path, ON)
    result = runner.invoke(app, ["send-to", "claude", "x" * (CLAUDE_MAX_CHARS + 1)])
    assert result.exit_code == 1
    assert "14,001" in result.output and "14,000" in result.output
    assert opener.calls == []


def test_a_client_that_did_not_open_exits_non_zero(monkeypatch, tmp_path):
    failing = _Opener(result=False)
    monkeypatch.setattr(handoff, "default_opener", failing)
    _platform(monkeypatch, tmp_path, ON)
    result = runner.invoke(app, ["send-to", "codex", "hi"])
    assert result.exit_code == 1
    assert "Nothing was sent" in result.output


def test_without_text_and_no_daemon_it_says_how_to_proceed(monkeypatch, tmp_path, opener):
    _platform(monkeypatch, tmp_path, ON, running=False)
    result = runner.invoke(app, ["send-to", "claude"])
    assert result.exit_code == 1
    assert "not running" in result.output
    assert opener.calls == []


def test_without_text_the_daemon_is_asked_by_target_only(monkeypatch, tmp_path, opener):
    calls: list[tuple[str, dict]] = []

    class _Client:
        def call(self, method, **params):
            calls.append((method, params))
            return {"ok": True, "message": "Opened Codex with 12 characters pre-filled."}

    _platform(monkeypatch, tmp_path, ON, running=True, client=_Client())
    result = runner.invoke(app, ["send-to", "codex"])
    assert result.exit_code == 0, result.output
    assert calls == [("send_to", {"target": "codex"})]
    assert "Opened Codex" in result.output
    assert opener.calls == [], "the daemon opens it, not the CLI"


def test_a_daemon_refusal_is_reported_and_exits_non_zero(monkeypatch, tmp_path, opener):
    class _Client:
        def call(self, method, **params):
            return {"ok": False, "reason": "empty",
                    "message": "Nothing to send — nothing is staged."}

    _platform(monkeypatch, tmp_path, ON, running=True, client=_Client())
    result = runner.invoke(app, ["send-to", "claude"])
    assert result.exit_code == 1
    assert "nothing is staged" in result.output


def test_an_older_daemon_without_the_method_is_explained(monkeypatch, tmp_path, opener):
    class _Client:
        def call(self, method, **params):
            raise IpcCallError(SimpleNamespace(code=-32601, message="Method not found"))

    _platform(monkeypatch, tmp_path, ON, running=True, client=_Client())
    result = runner.invoke(app, ["send-to", "claude"])
    assert result.exit_code == 1
    assert "yazses restart" in result.output
