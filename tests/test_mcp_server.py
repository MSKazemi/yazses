"""The stdio loop: real frames in, real frames out (ADR-020 §1).

Driven through injected streams rather than a subprocess, so a failure points at
a line of code instead of at a process that exited. What is proved here is the
framing — one JSON object per line, a flush after each, nothing on stdout that is
not protocol — because that is what a client actually depends on and what a stray
`print` silently breaks.
"""
from __future__ import annotations

import io
import json

from yazses.config import Config
from yazses.mcp.server import build_tools, serve


def _drive(lines: list[str]) -> list[dict]:
    out = io.StringIO()
    code = serve(Config(), stdin=io.StringIO("".join(f"{line}\n" for line in lines)), stdout=out)
    assert code == 0
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def _req(method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return json.dumps(body)


def test_a_full_handshake_then_a_tool_list() -> None:
    replies = _drive([
        _req("initialize", {"protocolVersion": "2025-06-18"}, rid=1),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        _req("tools/list", rid=2),
    ])
    assert [r["id"] for r in replies] == [1, 2], "the notification must not be answered"
    assert replies[0]["result"]["serverInfo"]["name"] == "yazses"
    assert [t["name"] for t in replies[1]["result"]["tools"]] == ["transcribe"]


def test_every_reply_is_one_line_of_json() -> None:
    """The transport is newline-delimited; a pretty-printed reply is unparseable."""
    out = io.StringIO()
    serve(Config(), stdin=io.StringIO(_req("tools/list") + "\n"), stdout=out)
    assert len(out.getvalue().strip().splitlines()) == 1


def test_unparseable_input_is_answered_not_fatal() -> None:
    """A client that writes a bad frame keeps its session: the server answers
    -32700 and reads the next line."""
    replies = _drive(["{not json", _req("tools/list", rid=7)])
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["id"] == 7, "the session survived the bad frame"


def test_a_json_array_is_rejected_as_a_request() -> None:
    """Batch requests are valid JSON-RPC and not part of MCP's stdio transport;
    accepting one would half-work in a way that is worse than refusing."""
    replies = _drive([json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])])
    assert replies[0]["error"]["code"] == -32600


def test_blank_lines_are_ignored() -> None:
    replies = _drive(["", "   ", _req("tools/list", rid=3)])
    assert len(replies) == 1 and replies[0]["id"] == 3


def test_a_missing_file_is_a_tool_error_and_the_server_lives() -> None:
    """The most likely real failure. It must read as content the model can act on,
    and must not end a session the client cannot restart."""
    replies = _drive([
        _req("tools/call", {"name": "transcribe", "arguments": {"path": "/nope/missing.wav"}}, rid=1),
        _req("tools/list", rid=2),
    ])
    assert replies[0]["result"]["isError"] is True
    assert replies[1]["id"] == 2, "the server survived the failed tool"


def test_ask_human_is_not_offered_until_it_works() -> None:
    """ADR-020 specifies it and it needs the daemon. A listed tool that always
    fails teaches a model to stop calling it — worse than not listing it."""
    assert [t.name for t in build_tools(Config())] == ["transcribe"]


def test_the_transcribe_schema_names_its_required_argument() -> None:
    schema = build_tools(Config())[0].schema
    assert schema["required"] == ["path"]
    assert "diarize" in schema["properties"]
