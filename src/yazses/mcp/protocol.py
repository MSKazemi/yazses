"""MCP request → response, with no I/O in sight (ADR-020 §1).

MCP is JSON-RPC 2.0 over stdio and this server answers three methods:
``initialize``, ``tools/list`` and ``tools/call``. Hand-written rather than taken
from an SDK — the surface is three methods, `ipc/protocol.py` already sets this
project's JSON-RPC conventions, and ADR-016's dependency budget makes a library
for that a poor trade. ADR-020 anticipated the question and left FastMCP as "an
implementation detail governed by ADR-016 like any other dependency".

The split that matters here is MCP's own, and clients depend on it:

* a **JSON-RPC error** means the call itself was wrong — unknown method,
  malformed frame. The client has a bug.
* a **result with ``isError``** means the tool ran and failed. That is ordinary
  content the model can read and react to, not a transport failure.

Getting those the wrong way round makes a missing file look like a broken server.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from yazses.ipc.protocol import INVALID_REQUEST, JSONRPC_VERSION, METHOD_NOT_FOUND

#: What this server implements. A client that asks for another revision is
#: answered in its own — it cannot downgrade after the handshake, and the three
#: methods here have been stable across revisions.
PROTOCOL_VERSION = "2025-06-18"

SERVER_INFO = {"name": "yazses", "title": "YazSes"}


@dataclass(frozen=True)
class ToolSpec:
    """One exposed tool: what it is called, what it takes, and what runs it."""

    name: str
    description: str
    schema: dict[str, Any]
    run: Callable[..., Any]


def _text(body: str, *, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": body}]}
    if is_error:
        result["isError"] = True
    return result


def _error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": rid, "error": {"code": code, "message": message}}


def _ok(rid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": rid, "result": result}


def handle(request: dict[str, Any], tools: tuple[ToolSpec, ...]) -> dict[str, Any] | None:
    """Answer one MCP request, or ``None`` when it is a notification.

    Notifications (no ``id``) must go unanswered: replying to one is a protocol
    violation, and some clients treat it as a fatal framing error and hang up.
    """
    rid = request.get("id")
    method = request.get("method")

    if not isinstance(method, str):
        return _error(rid, INVALID_REQUEST, "Request has no method.")

    if rid is None:
        return None  # a notification — acknowledged by saying nothing

    if method == "initialize":
        params = request.get("params") or {}
        return _ok(rid, {
            # Echo the client's revision. Telling it a newer one leaves it unable
            # to adapt, since the handshake is already over by the time it reads
            # this.
            "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })

    if method == "tools/list":
        return _ok(rid, {"tools": [
            {"name": t.name, "description": t.description, "inputSchema": t.schema}
            for t in tools
        ]})

    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        chosen = next((t for t in tools if t.name == name), None)
        if chosen is None:
            offered = ", ".join(t.name for t in tools) or "none"
            return _ok(rid, _text(
                f"No tool named {name!r}. This server offers: {offered}.", is_error=True
            ))
        try:
            outcome = chosen.run(**(params.get("arguments") or {}))
        except Exception as exc:  # noqa: BLE001 - a failed tool is a result, not a crash
            # Never propagate: this is a long-lived stdio process and the client
            # cannot restart it mid-session, so one bad argument must not end it.
            return _ok(rid, _text(f"{type(exc).__name__}: {exc}", is_error=True))
        return _ok(rid, _text(outcome if isinstance(outcome, str) else repr(outcome)))

    return _error(rid, METHOD_NOT_FOUND, f"Unknown method: {method!r}")
