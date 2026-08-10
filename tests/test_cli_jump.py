from __future__ import annotations

import pytest
from typer.testing import CliRunner

from yazses.cli import app


@pytest.fixture
def fake_bridge(monkeypatch):
    from yazses.commands import lsp_context as lsp_mod

    class FakeBridge:
        def __init__(self):
            self.motions = []

        def connect(self):
            return True

        def get_context(self):
            return None

        def get_symbols(self):
            return {"main": 10, "Helper": 42}

        def apply_motion(self, kind, payload):
            self.motions.append((kind, payload))
            return True

    bridge = FakeBridge()

    def _build(self, editor: str):
        return bridge

    monkeypatch.setattr(lsp_mod.LspContextProvider, "_build_bridge", _build)
    return bridge


def test_jump_line(fake_bridge):
    runner = CliRunner()
    result = runner.invoke(app, ["jump", "go to line 42"])
    assert result.exit_code == 0
    assert fake_bridge.motions == [("goto_line", 42)]


def test_jump_symbol(fake_bridge):
    runner = CliRunner()
    result = runner.invoke(app, ["jump", "jump to symbol Helper"])
    assert result.exit_code == 0
    assert fake_bridge.motions == [("goto_line", 42)]


def test_jump_invalid_target(fake_bridge):
    runner = CliRunner()
    result = runner.invoke(app, ["jump", "something random that fails"])
    assert result.exit_code == 1
    assert "Could not parse jump target" in result.output
    assert fake_bridge.motions == []
