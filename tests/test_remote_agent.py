"""Tests for the yazses-agent JSON-RPC handler."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest


def make_mock_injector(inject_fn=None):
    m = MagicMock()
    if inject_fn:
        m.inject.side_effect = inject_fn
    return m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_writer():
    """Return a writer mock and a bytearray that collects what was written."""
    buf = bytearray()
    writer = MagicMock()
    writer.write = lambda data: buf.extend(data)

    async def mock_drain():
        pass

    writer.drain = mock_drain
    writer.close = MagicMock()
    return writer, buf


def _make_reader(payload: str) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data((payload + "\n").encode())
    reader.feed_eof()
    return reader


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_agent_inject_calls_injector():
    """inject(text) RPC should call injector.inject(text)."""
    from yazses.remote.agent import _handle_client

    injector = make_mock_injector()
    request = json.dumps({"jsonrpc": "2.0", "method": "inject", "params": {"text": "hello world"}, "id": 1})

    async def _run():
        reader = _make_reader(request)
        writer, buf = _make_writer()
        await _handle_client(reader, writer, injector)

    asyncio.run(_run())
    injector.inject.assert_called_once_with("hello world")


def test_agent_ping_responds():
    """ping method should return pong: True."""
    from yazses.remote.agent import _handle_client

    injector = make_mock_injector()
    request = json.dumps({"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 2})

    writer_data = bytearray()

    async def _run():
        reader = _make_reader(request)
        writer, buf = _make_writer()
        await _handle_client(reader, writer, injector)
        writer_data.extend(buf)

    asyncio.run(_run())
    response = json.loads(writer_data.decode().strip())
    assert response["result"]["pong"] is True


def test_agent_unknown_method_returns_error():
    """Unknown method should return JSON-RPC error -32601."""
    from yazses.remote.agent import _handle_client

    injector = make_mock_injector()
    request = json.dumps({"jsonrpc": "2.0", "method": "nonexistent", "params": {}, "id": 3})

    writer_data = bytearray()

    async def _run():
        reader = _make_reader(request)
        writer, buf = _make_writer()
        await _handle_client(reader, writer, injector)
        writer_data.extend(buf)

    asyncio.run(_run())
    response = json.loads(writer_data.decode().strip())
    assert "error" in response
    assert response["error"]["code"] == -32601


def test_agent_inject_error_returns_rpc_error():
    """If injector.inject() raises, the agent should return JSON-RPC -32603."""
    from yazses.remote.agent import _handle_client

    injector = make_mock_injector(inject_fn=RuntimeError("boom"))
    request = json.dumps({"jsonrpc": "2.0", "method": "inject", "params": {"text": "hi"}, "id": 4})

    writer_data = bytearray()

    async def _run():
        reader = _make_reader(request)
        writer, buf = _make_writer()
        await _handle_client(reader, writer, injector)
        writer_data.extend(buf)

    asyncio.run(_run())
    response = json.loads(writer_data.decode().strip())
    assert "error" in response
    assert response["error"]["code"] == -32603


def test_agent_malformed_json_returns_parse_error():
    """Malformed JSON should return JSON-RPC parse error -32700."""
    from yazses.remote.agent import _handle_client

    injector = make_mock_injector()

    writer_data = bytearray()

    async def _run():
        reader = _make_reader("{not valid json")
        writer, buf = _make_writer()
        await _handle_client(reader, writer, injector)
        writer_data.extend(buf)

    asyncio.run(_run())
    response = json.loads(writer_data.decode().strip())
    assert "error" in response
    assert response["error"]["code"] == -32700


def test_remote_injector_proxy_is_reachable_false():
    """RemoteInjectorProxy.is_reachable() returns False when nothing is listening."""
    from yazses.remote.local_proxy import RemoteInjectorProxy
    proxy = RemoteInjectorProxy(host="127.0.0.1", port=19999)
    assert proxy.is_reachable() is False


def test_forwarder_raises_on_missing_ssh():
    """RemoteForwarder.connect() should raise FileNotFoundError if ssh not found."""
    import unittest.mock as mock

    from yazses.remote.forwarder import RemoteForwarder
    forwarder = RemoteForwarder()
    with mock.patch("shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError, match="ssh is not installed"):
            forwarder.connect("user@example.com")
