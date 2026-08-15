"""The MCP handshake and tool dispatch, as pure request → response (ADR-020 §1).

MCP is JSON-RPC 2.0 over stdio: `initialize`, then `tools/list`, then
`tools/call`. Written by hand rather than pulled from an SDK — the whole surface
is three methods, and `yazses/ipc/protocol.py` already establishes how this
project frames JSON-RPC. ADR-016's dependency budget makes a library for three
methods a poor trade, and ADR-020 explicitly leaves FastMCP as "an implementation
detail governed by ADR-016 like any other dependency".

Kept pure so the protocol is testable without spawning a process or wiring stdin:
every test here is a dict in and a dict out.
"""
from __future__ import annotations

from yazses.mcp.protocol import ToolSpec, handle


def _echo(**kwargs):
    return {"echoed": kwargs}


TOOLS = (
    ToolSpec(
        name="transcribe",
        description="Transcribe an audio file offline.",
        schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        run=_echo,
    ),
)


def _req(method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return body


def test_initialize_reports_the_protocol_and_the_server() -> None:
    reply = handle(_req("initialize", {"protocolVersion": "2025-06-18"}), TOOLS)
    assert reply["result"]["serverInfo"]["name"] == "yazses"
    assert reply["result"]["protocolVersion"]
    assert reply["result"]["capabilities"]["tools"] == {}


def test_initialize_echoes_the_clients_protocol_version() -> None:
    """A client that speaks an older revision must not be told a newer one — it
    has no way to downgrade after the handshake."""
    reply = handle(_req("initialize", {"protocolVersion": "2024-11-05"}), TOOLS)
    assert reply["result"]["protocolVersion"] == "2024-11-05"


def test_tools_list_returns_the_schemas() -> None:
    reply = handle(_req("tools/list"), TOOLS)
    tools = reply["result"]["tools"]
    assert [t["name"] for t in tools] == ["transcribe"]
    assert tools[0]["inputSchema"]["required"] == ["path"]


def test_calling_a_tool_runs_it_and_wraps_the_result_as_content() -> None:
    reply = handle(_req("tools/call", {"name": "transcribe", "arguments": {"path": "a.wav"}}), TOOLS)
    content = reply["result"]["content"]
    assert content[0]["type"] == "text"
    assert "a.wav" in content[0]["text"]
    assert reply["result"].get("isError") in (None, False)


def test_an_unknown_tool_is_an_error_result_not_a_protocol_error() -> None:
    """MCP distinguishes the two, and clients rely on it: a protocol error means
    the *call* was malformed, while a failed tool is a normal result the model can
    read and react to."""
    reply = handle(_req("tools/call", {"name": "nope", "arguments": {}}), TOOLS)
    assert "error" not in reply
    assert reply["result"]["isError"] is True
    assert "nope" in reply["result"]["content"][0]["text"]


def test_a_tool_that_raises_becomes_an_error_result_not_a_crash() -> None:
    """One bad call must not take the server down: it is a long-lived stdio
    process, and the client has no way to restart it mid-session."""
    def _boom(**kwargs):
        raise RuntimeError("no such file")

    tools = (ToolSpec(name="boom", description="", schema={}, run=_boom),)
    reply = handle(_req("tools/call", {"name": "boom", "arguments": {}}), tools)
    assert reply["result"]["isError"] is True
    assert "no such file" in reply["result"]["content"][0]["text"]


def test_an_unknown_method_is_a_jsonrpc_error() -> None:
    reply = handle(_req("resources/list"), TOOLS)
    assert reply["error"]["code"] == -32601


def test_a_notification_gets_no_reply() -> None:
    """`notifications/initialized` has no id. Replying to a notification is a
    protocol violation and some clients hang up on it."""
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, TOOLS) is None


def test_a_malformed_request_is_reported_not_raised() -> None:
    reply = handle({"jsonrpc": "2.0", "id": 4}, TOOLS)
    assert reply["error"]["code"] == -32600


def test_the_id_is_echoed_so_a_client_can_match_replies() -> None:
    reply = handle(_req("tools/list", rid="abc"), TOOLS)
    assert reply["id"] == "abc"
