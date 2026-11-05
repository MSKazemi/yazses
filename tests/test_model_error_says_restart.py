"""A missing speech model must not be a dead end (GUI audit A3, v2.49.0).

The daemon holds an error state after a failed model load and never retries, so every
instruction that ends with the model on disk must also say `yazses restart`; the first
line is what the tray tooltip shows (cut short), so it must carry the cause and the fix.
The CLI is exercised offline: the download is mocked.
"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.stt.errors import ModelUnavailableError, model_unavailable_message

runner = CliRunner()


@pytest.mark.parametrize("cause", [OSError("boom"), "WinError 10013 blocked"])
def test_every_fix_line_that_does_not_restart_itself_says_restart(cause):
    msg = model_unavailable_message("base.en", cause)
    start = msg.index("Any one of these fixes it:")
    end = msg.index("Dictation stays unavailable")
    fixes = msg[start:end].split("\n")[1:]
    # A fix is a numbered line plus its indented continuation lines, up to the next number.
    blocks: list[list[str]] = []
    for line in fixes:
        if line.lstrip()[:2] in ("1.", "2.", "3."):
            blocks.append([line])
        elif line.strip() and blocks:
            blocks[-1].append(line)
    assert len(blocks) == 3
    for block in blocks:
        assert "restart" in " ".join(block), block


def test_the_first_line_leads_with_the_cause_and_the_short_fix():
    first = model_unavailable_message("base.en", OSError("boom")).split("\n")[0]
    assert first.startswith("Speech model 'base.en' missing")
    assert "yazses model download base.en" in first
    assert "yazses restart" in first


def test_the_toast_body_says_restart_too():
    _title, body = ModelUnavailableError("base.en", OSError("x")).notification()
    assert "yazses restart" in body


class _Lifecycle:
    def __init__(self, running):
        self._running = running

    def is_running(self):
        return self._running


class _Paths:
    config_file = "/nonexistent/yazses-test-config.toml"


class _Platform:
    def __init__(self, running):
        self.lifecycle = _Lifecycle(running)
        self.paths = _Paths()


def _download(monkeypatch, tmp_path, *, running, configured="base.en"):
    import yazses.stt.download as download

    monkeypatch.setattr(download, "is_cached", lambda *a, **k: False)
    monkeypatch.setattr(download, "download_stt_model", lambda m, echo=None: tmp_path / m)
    monkeypatch.setattr(cli, "get_platform", lambda: _Platform(running))
    monkeypatch.setattr(cli, "_configured_model", lambda platform: configured)
    return runner.invoke(cli.app, ["model", "download", "base.en"])


def test_download_tells_a_running_daemon_to_restart(monkeypatch, tmp_path):
    result = _download(monkeypatch, tmp_path, running=True)
    assert result.exit_code == 0, result.output
    assert "Done." in result.output
    assert "yazses restart" in result.output


def test_download_stays_quiet_about_restart_when_no_daemon_runs(monkeypatch, tmp_path):
    result = _download(monkeypatch, tmp_path, running=False)
    assert result.exit_code == 0, result.output
    assert "Done." in result.output
    assert "restart" not in result.output


def test_download_of_a_model_the_daemon_does_not_use_does_not_say_restart(
    monkeypatch, tmp_path
):
    result = _download(monkeypatch, tmp_path, running=True, configured="small.en")
    assert result.exit_code == 0, result.output
    assert "restart" not in result.output
