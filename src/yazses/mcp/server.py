"""The stdio loop and the tools it exposes (ADR-020 §1).

Newline-delimited JSON on stdin/stdout, which is what MCP's stdio transport is and
what `ipc/` already speaks. **stdout carries the protocol and nothing else** — a
stray `print` corrupts the stream and the client sees a parse error rather than a
message, so every diagnostic goes to stderr.

Stdio is the security property, not a convenience. ADR-020 §2: YazSes's own IPC is
an ``AF_UNIX`` socket, unreachable from another machine *by construction* rather
than by configuration. A stdio server inherits that — it is a child process of
whatever spawned it, with no port, no bind address and no firewall rule between a
user's dictation and the network.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, TextIO

from yazses.mcp.protocol import ToolSpec, handle

log = logging.getLogger(__name__)


def transcribe_tool(config) -> ToolSpec:
    """`transcribe(path)` — an offline transcript of a file.

    ADR-020: "useful, unglamorous, and already the CLI; exposing it costs nothing
    new." It reads a file the caller already has and returns text; it does not
    touch the microphone, the focused window, or the network.
    """
    def _run(path: str, diarize: bool = False) -> str:
        from yazses.recimport.pipeline import transcribe_file

        result = transcribe_file(path, config)
        segments = getattr(result, "utterances", None) or []
        if diarize and segments:
            return "\n".join(
                f"{getattr(u, 'speaker', '?')}: {getattr(u, 'text', '')}".strip()
                for u in segments
            )
        text = getattr(result, "text", None)
        if text:
            return text
        return "\n".join(getattr(u, "text", "") for u in segments).strip()

    return ToolSpec(
        name="transcribe",
        description=(
            "Transcribe an audio or video file to text, entirely on this machine. "
            "Nothing is uploaded. Optionally tag who said what."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the audio or video file."},
                "diarize": {
                    "type": "boolean",
                    "description": "Label each line with a speaker (needs the diarization extra).",
                },
            },
            "required": ["path"],
        },
        run=_run,
    )


def build_tools(config) -> tuple[ToolSpec, ...]:
    """The tools this server offers.

    Only `transcribe` for now. ADR-020 specifies a second — `ask_human`, the one
    genuinely novel thing here — and it needs the daemon, which owns the
    microphone and knows whether the user is mid-hold. Listing it before it works
    would be worse than not listing it: a model would call it, and a tool that
    always fails teaches the model to stop trying.
    """
    return (transcribe_tool(config),)


def serve(config, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Read requests until stdin closes. Returns a process exit code.

    Streams are injectable so the loop is testable without a subprocess.
    """
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    tools = build_tools(config)

    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            # -32700 per JSON-RPC. Answered with a null id because the id lives
            # inside the frame we could not parse.
            _write(sink, {"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32700, "message": "Invalid JSON."}})
            continue

        if not isinstance(request, dict):
            _write(sink, {"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32600, "message": "Request must be an object."}})
            continue

        reply = handle(request, tools)
        if reply is not None:
            _write(sink, reply)
    return 0


def _write(sink: TextIO, payload: dict[str, Any]) -> None:
    """One frame, flushed. Without the flush a pipe buffers the reply and the
    client waits for a response that has already been written."""
    sink.write(json.dumps(payload) + "\n")
    sink.flush()
