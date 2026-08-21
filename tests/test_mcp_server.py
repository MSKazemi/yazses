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


# --- ask_human appears only when switched on ---------------------------------


def test_ask_human_is_offered_when_enabled() -> None:
    cfg = Config()
    object.__setattr__(cfg.mcp, "ask_human", True)
    assert [t.name for t in build_tools(cfg)] == ["transcribe", "ask_human"]


def test_ask_human_is_absent_by_default() -> None:
    """Off by default like everything, and doubly so for a tool that can interrupt
    someone. A listed tool that always refuses teaches a model to stop calling it."""
    assert "ask_human" not in [t.name for t in build_tools(Config())]


def test_the_ask_human_schema_requires_a_question() -> None:
    cfg = Config()
    object.__setattr__(cfg.mcp, "ask_human", True)
    schema = [t for t in build_tools(cfg) if t.name == "ask_human"][0].schema
    assert schema["required"] == ["question"]
    assert "timeout_s" in schema["properties"]


def test_a_stopped_daemon_is_reported_as_text_not_a_crash(monkeypatch) -> None:
    """Nobody to ask is an ordinary answer for a model to read, not a transport
    failure — and the server must survive it, since the client cannot restart it."""
    from yazses.mcp import server as server_mod

    cfg = Config()
    object.__setattr__(cfg.mcp, "ask_human", True)
    tool = [t for t in build_tools(cfg) if t.name == "ask_human"][0]

    class _Down:
        def call(self, *a, **k):
            from yazses.ipc.client import IpcUnreachableError

            raise IpcUnreachableError("not listening")

    monkeypatch.setattr(
        server_mod, "get_platform", lambda: _FakePlatform(_Down()), raising=False
    )
    import yazses.platform as platform_mod

    monkeypatch.setattr(platform_mod, "get_platform", lambda: _FakePlatform(_Down()))
    out = tool.run(question="ready?")
    assert "not running" in out.lower()


class _FakePlatform:
    def __init__(self, client):
        self._client = client

    @property
    def paths(self):
        import types

        return types.SimpleNamespace(ipc_socket="/tmp/nope.sock")

    def ipc_client_factory(self, _socket):
        return self._client


# --- the transport is stdio, and stays stdio ----------------------------------


def test_the_mcp_package_cannot_reach_the_network() -> None:
    """ADR-019's egress inventory is the real guard here, and it already fails on a
    `socket`/`http`/`urllib` import anywhere under `src/yazses/` — verified by adding
    one to this module and watching `test_no_undeclared_module_can_reach_the_network`
    go red.

    This states the property where an MCP contributor would look for it. An agent
    bridge is the natural place for someone to reach for "just expose it on a port",
    and the whole design rests on it being a pipe between two processes on this
    machine: an HTTP listener is a hole in ADR-011 that no config flag makes safe.
    """
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parent.parent / "src/yazses/mcp"
    modules = sorted(package.glob("*.py"))
    assert len(modules) >= 3, f"only found {modules} — this guard would be vacuous"

    network = {"socket", "socketserver", "http", "urllib", "requests", "httpx", "aiohttp"}
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            offending = network.intersection(names)
            assert not offending, (
                f"{path.name} imports {sorted(offending)}. The MCP bridge is stdio "
                f"between two processes on this machine; a listener would put the "
                f"user's dictation on a port."
            )


def test_serve_reads_the_streams_it_is_given() -> None:
    """The transport is injectable, which is what makes the above testable at all —
    and is why the server needs no socket to be exercised."""
    import io

    from yazses.config import Config
    from yazses.mcp.server import serve

    stdin = io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
    )
    stdout = io.StringIO()
    code = serve(Config(), stdin=stdin, stdout=stdout)

    assert code == 0
    assert '"jsonrpc"' in stdout.getvalue(), stdout.getvalue()
