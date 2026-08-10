"""Tests for LSP context provider (yazses.commands.lsp_context).

All tests avoid importing pynvim; the real library is never required.
"""
from __future__ import annotations

import time

# ---------------------------------------------------------------------------
# NullBridge
# ---------------------------------------------------------------------------


def test_null_bridge_connect_returns_false():
    from yazses.commands.lsp_context import NullBridge

    bridge = NullBridge()
    assert bridge.connect() is False


def test_null_bridge_get_context_returns_none():
    from yazses.commands.lsp_context import NullBridge

    bridge = NullBridge()
    assert bridge.get_context() is None


def test_null_bridge_methods():
    from yazses.commands.lsp_context import NullBridge

    bridge = NullBridge()
    assert bridge.get_symbols() == {}
    assert bridge.apply_motion("goto_line", 10) is False


# ---------------------------------------------------------------------------
# CodeContext.to_prompt_string
# ---------------------------------------------------------------------------


def test_code_context_to_prompt_string():
    from yazses.commands.lsp_context import CodeContext

    ctx = CodeContext(
        language_id="python",
        file_path="/project/src/main.py",
        scope_chain=["class BatchProcessor", "method process_batch"],
        recent_identifiers=["batch_size", "record_count"],
        cursor_line=42,
    )
    prompt = ctx.to_prompt_string()
    assert "python" in prompt
    assert "BatchProcessor" in prompt
    assert "process_batch" in prompt
    assert "batch_size" in prompt
    assert "record_count" in prompt


def test_code_context_to_prompt_empty_scope():
    """When scope_chain is empty the 'Scope' line must be absent from the prompt."""
    from yazses.commands.lsp_context import CodeContext

    ctx = CodeContext(
        language_id="go",
        file_path="/srv/main.go",
        scope_chain=[],
        recent_identifiers=["httpClient", "retryCount"],
        cursor_line=10,
    )
    prompt = ctx.to_prompt_string()
    assert "Scope" not in prompt
    assert "go" in prompt
    assert "httpClient" in prompt


def test_code_context_to_prompt_truncates_identifiers():
    """to_prompt_string must include only the first 10 identifiers."""
    from yazses.commands.lsp_context import CodeContext

    identifiers = [f"ident_{i}" for i in range(20)]
    ctx = CodeContext(
        language_id="typescript",
        file_path="/app/index.ts",
        scope_chain=["class App"],
        recent_identifiers=identifiers,
        cursor_line=1,
    )
    prompt = ctx.to_prompt_string()
    # First 10 must appear.
    for i in range(10):
        assert f"ident_{i}" in prompt
    # Identifiers 10-19 must not appear.
    for i in range(10, 20):
        assert f"ident_{i}" not in prompt


def test_code_context_to_prompt_no_identifiers():
    """When recent_identifiers is empty the 'Recent identifiers' line must be absent."""
    from yazses.commands.lsp_context import CodeContext

    ctx = CodeContext(
        language_id="rust",
        file_path="/project/src/lib.rs",
        scope_chain=["impl Parser"],
        recent_identifiers=[],
        cursor_line=5,
    )
    prompt = ctx.to_prompt_string()
    assert "Recent identifiers" not in prompt
    assert "rust" in prompt


# ---------------------------------------------------------------------------
# LspContextProvider — auto-detection with no editor
# ---------------------------------------------------------------------------


def test_provider_returns_none_no_nvim(monkeypatch):
    """When $NVIM is unset the provider must use NullBridge and return None."""
    monkeypatch.delenv("NVIM", raising=False)

    from yazses.commands.lsp_context import LspContextProvider

    provider = LspContextProvider(editor="auto")
    result = provider.get_context(timeout_ms=50)
    assert result is None


def test_provider_unknown_editor_returns_none(monkeypatch):
    """An unknown editor string must fall back to NullBridge and return None."""
    monkeypatch.delenv("NVIM", raising=False)

    from yazses.commands.lsp_context import LspContextProvider

    provider = LspContextProvider(editor="emacs")
    result = provider.get_context(timeout_ms=50)
    assert result is None


# ---------------------------------------------------------------------------
# LspContextProvider — timeout
# ---------------------------------------------------------------------------


def test_provider_timeout_returns_none(monkeypatch):
    """A bridge that hangs longer than timeout_ms must cause get_context to return None."""
    monkeypatch.setenv("NVIM", "/fake/nvim.sock")

    from yazses.commands import lsp_context as lsp_mod

    class SlowBridge:
        # _build_bridge calls NeovimBridge(socket_path), so accept a positional arg.
        def __init__(self, socket_path: str = "") -> None:
            pass

        def connect(self) -> bool:
            # Connect succeeds so _build_bridge returns this bridge.
            return True

        def get_context(self):
            time.sleep(0.5)  # Much longer than the 100 ms timeout.
            return None

    monkeypatch.setattr(lsp_mod, "NeovimBridge", SlowBridge)

    provider = lsp_mod.LspContextProvider(editor="auto")
    result = provider.get_context(timeout_ms=100)
    assert result is None


def test_provider_bridge_exception_returns_none(monkeypatch):
    """When the bridge raises an exception get_context must return None, not propagate."""
    monkeypatch.delenv("NVIM", raising=False)

    from yazses.commands import lsp_context as lsp_mod

    class BrokenBridge:
        def connect(self) -> bool:
            return True

        def get_context(self):
            raise RuntimeError("pynvim crashed")

    def _inject_broken_bridge(self, editor: str):
        return BrokenBridge()

    monkeypatch.setattr(lsp_mod.LspContextProvider, "_build_bridge", _inject_broken_bridge)

    provider = lsp_mod.LspContextProvider(editor="auto")
    result = provider.get_context(timeout_ms=200)
    assert result is None


# ---------------------------------------------------------------------------
# LspContextProvider — successful path via a stub bridge
# ---------------------------------------------------------------------------


def test_provider_returns_context_from_stub(monkeypatch):
    """When the bridge returns a CodeContext the provider must pass it through."""
    monkeypatch.delenv("NVIM", raising=False)

    from yazses.commands import lsp_context as lsp_mod
    from yazses.commands.lsp_context import CodeContext

    expected = CodeContext(
        language_id="python",
        file_path="/tmp/foo.py",
        scope_chain=["class Foo"],
        recent_identifiers=["bar", "baz"],
        cursor_line=7,
    )

    class ImmediateBridge:
        def connect(self) -> bool:
            return True

        def get_context(self):
            return expected

    def _inject(self, editor: str):
        return ImmediateBridge()

    monkeypatch.setattr(lsp_mod.LspContextProvider, "_build_bridge", _inject)

    provider = lsp_mod.LspContextProvider(editor="auto")
    result = provider.get_context(timeout_ms=200)
    assert result is expected


def test_bridge_get_symbols_and_apply_motion_stub(monkeypatch):
    """Test get_symbols and apply_motion on LspContextProvider."""
    monkeypatch.delenv("NVIM", raising=False)

    from yazses.commands import lsp_context as lsp_mod

    class StubBridge:
        def connect(self) -> bool:
            return True
        def get_context(self):
            return None
        def get_symbols(self) -> dict[str, int]:
            return {"main": 10, "Helper": 42}
        def apply_motion(self, kind: str, payload: object) -> bool:
            return kind == "goto_line" and payload == 10

    def _inject(self, editor: str):
        return StubBridge()

    monkeypatch.setattr(lsp_mod.LspContextProvider, "_build_bridge", _inject)

    provider = lsp_mod.LspContextProvider(editor="auto")
    bridge = provider._bridge
    assert bridge.get_symbols() == {"main": 10, "Helper": 42}
    assert bridge.apply_motion("goto_line", 10) is True
    assert bridge.apply_motion("goto_symbol", "main") is False
