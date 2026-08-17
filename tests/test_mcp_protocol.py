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


# ---- a bad call is answered from the schema, not by Python -------------------


def _call(tools, **params):
    return handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}, tools)


class _Tool:
    name = "transcribe"
    description = "Transcribe a file."
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}, "diarize": {"type": "boolean"}},
        "required": ["path"],
    }

    @staticmethod
    def run(path, diarize=False):
        return f"transcribed {path}"


def test_a_missing_argument_is_explained_from_the_schema():
    """The model on the other end used to be handed a Python traceback string:

        TypeError: transcribe_tool.<locals>._run() missing 1 required
        positional argument: 'path'

    An internal closure name, from which it has to guess the field it omitted.
    The schema that `tools/list` already publishes says exactly what is required,
    so the error answers from that.
    """
    reply = _call([_Tool()], name="transcribe")
    text = reply["result"]["content"][0]["text"]

    assert reply["result"]["isError"] is True
    assert "path" in text, text
    assert "Required: path" in text
    assert "Accepts: path, diarize" in text
    assert "<locals>" not in text and "TypeError" not in text, (
        f"Python internals reached the caller: {text}"
    )


def test_a_missing_tool_name_says_which_field_is_missing():
    """"No tool named None" reads as though None were a name that was tried."""
    reply = _call([_Tool()], arguments={})
    text = reply["result"]["content"][0]["text"]
    assert reply["result"]["isError"] is True
    assert "needs a 'name'" in text, text
    assert "None" not in text, f"Python's None leaked into the message: {text}"


def test_an_unknown_tool_still_lists_what_is_offered():
    reply = _call([_Tool()], name="nope", arguments={})
    text = reply["result"]["content"][0]["text"]
    assert "No tool named 'nope'" in text and "transcribe" in text


def test_a_good_call_still_runs():
    """The binding check must not cost the ordinary path anything."""
    reply = _call([_Tool()], name="transcribe", arguments={"path": "/tmp/a.wav"})
    assert not reply["result"].get("isError")
    assert "transcribed /tmp/a.wav" in reply["result"]["content"][0]["text"]


def test_an_error_inside_the_tool_is_still_reported_as_a_result():
    """A failing tool must not end a long-lived stdio session."""
    class _Boom(_Tool):
        @staticmethod
        def run(path, diarize=False):
            raise RuntimeError("decode failed")

    reply = _call([_Boom()], name="transcribe", arguments={"path": "/tmp/a.wav"})
    assert reply["result"]["isError"] is True
    assert "decode failed" in reply["result"]["content"][0]["text"]
