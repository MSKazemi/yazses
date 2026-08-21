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


def ask_human_tool(config) -> ToolSpec:
    """`ask_human(question, timeout_s)` — ask the person out loud, get their answer.

    Forwarded to the daemon over IPC rather than done here, because the daemon
    owns the microphone, knows whether a hold is in progress, and owns the
    injector that must not fire. This process owns none of those.

    A refusal comes back as ordinary text rather than an exception: "you have used
    this hour's questions" and "the user is speaking right now" are things a model
    should read and act on, not transport failures.
    """
    def _run(question: str, timeout_s: float = 30.0) -> str:
        from yazses.ipc.client import IpcUnreachableError
        from yazses.platform import get_platform

        platform = get_platform()
        client = platform.ipc_client_factory(platform.paths.ipc_socket)
        try:
            # `call` takes keyword params, not a dict — passing a dict makes it a
            # positional argument and raises TypeError before the socket is
            # touched. Caught by running it against the live daemon; the unit
            # tests used a fake client that accepted anything.
            reply = client.call(
                "ask_human", question=question, timeout_s=timeout_s, caller="mcp"
            )
        except IpcUnreachableError:
            return (
                "YazSes is not running, so nobody can be asked. Start it with "
                "`yazses start`."
            )
        if reply.get("ok"):
            return str(reply.get("answer") or "")
        reason = str(reply.get("reason") or "The question was not asked.")
        wait = reply.get("retry_after_s")
        return f"{reason}" + (f" (try again in about {round(float(wait))}s)" if wait else "")

    return ToolSpec(
        name="ask_human",
        description=(
            "Ask the person at this machine a question out loud and return their "
            "spoken answer. Use it when you are stuck on a decision only a human "
            "can make — authorisation, ambiguity, taste. Interrupts are rate-limited "
            "and may be refused; read the reply rather than retrying."
        ),
        schema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Asked aloud, verbatim."},
                "timeout_s": {
                    "type": "number",
                    "description": "How long to listen for an answer. Capped by the daemon.",
                },
            },
            "required": ["question"],
        },
        run=_run,
    )


def build_tools(config) -> tuple[ToolSpec, ...]:
    """The tools this server offers — ADR-020's two, and no more.

    `ask_human` appears only when it is switched on. A tool that is listed and
    always refuses teaches a model to stop calling it, which would waste the one
    genuinely novel thing on offer; and off-by-default is the rule for every
    feature here, doubly so for one that can interrupt someone.
    """
    tools = [transcribe_tool(config)]
    if getattr(getattr(config, "mcp", None), "ask_human", False):
        tools.append(ask_human_tool(config))
    return tuple(tools)


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
