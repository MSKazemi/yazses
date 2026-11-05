"""A deeply nested frame must cost one error reply, never the session.

``json.loads`` of a few tens of thousands of ``[`` raises ``RecursionError`` (not a
``ValueError``). The stdio loop caught only ``ValueError``, so one such line ended
``serve()``, and the client -- which cannot restart this process mid-session -- lost the
server. The IPC server already answers the equivalent frame; this holds the MCP loop to
the same standard.

Payloads are built by string repetition, never by ``json.dumps`` of a nested object,
because the test itself must not recurse.
"""
from __future__ import annotations

import io
import json

import pytest

from yazses.config import Config
from yazses.mcp.server import serve

DEPTH = 100_000


def _drive_raw(lines: list[str]) -> list[dict]:
    out = io.StringIO()
    code = serve(Config(), stdin=io.StringIO("".join(f"{line}\n" for line in lines)), stdout=out)
    assert code == 0
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def _deep_array() -> str:
    return "[" * DEPTH


def _deep_object() -> str:
    return '{"a":' * DEPTH + "1" + "}" * DEPTH


_TOOLS_LIST = '{"jsonrpc":"2.0","id":7,"method":"tools/list"}'

_FRAMES = {
    "deep array": _deep_array(),
    "deep array, closed": "[" * DEPTH + "]" * DEPTH,
    "deep object": _deep_object(),
    "deep params": '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
    + "[" * DEPTH + "]" * DEPTH + "}",
    "deep params object": '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
    + _deep_object() + "}",
    "deep arguments": '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
    '{"name":"transcribe","arguments":{"path":' + "[" * DEPTH + "]" * DEPTH + "}}}",
    "deep id": '{"jsonrpc":"2.0","id":' + "[" * DEPTH + "]" * DEPTH + ',"method":"tools/list"}',
    "deep protocolVersion": '{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
    '{"protocolVersion":' + "[" * DEPTH + "]" * DEPTH + "}}",
}


@pytest.mark.parametrize("name", list(_FRAMES))
def test_a_deeply_nested_frame_is_answered_and_the_loop_continues(name: str) -> None:
    replies = _drive_raw([_FRAMES[name], _TOOLS_LIST])
    assert replies, "the deep frame and the next line must both be handled"
    last = replies[-1]
    assert last["id"] == 7 and "tools" in last["result"], "the loop must reach the next line"
    for reply in replies[:-1]:
        # Whatever the deep frame produced is a well-formed JSON-RPC reply, an error
        # or a tool-level result, never a traceback or a closed stream.
        assert reply["jsonrpc"] == "2.0"
        assert "error" in reply or "result" in reply


def test_a_deep_array_line_is_a_parse_error_with_a_null_id() -> None:
    replies = _drive_raw([_deep_array(), _TOOLS_LIST])
    assert replies[0]["id"] is None
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["id"] == 7


def test_a_deep_frame_does_not_reflect_its_content() -> None:
    replies = _drive_raw([_FRAMES["deep object"], _TOOLS_LIST])
    assert len(json.dumps(replies[0])) < 500
