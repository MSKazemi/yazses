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
    def _run(path: str, diarize: bool | None = None) -> str:
        import dataclasses

        from yazses.recimport.pipeline import transcribe_file

        # The `[recimport]` section and `[stt]`, exactly as `yazses transcribe` passes
        # them. This used to hand over the whole `Config`, which every field lookup
        # downstream answers with its default: the tool decoded `small.en` in English
        # whatever the user had configured, and `diarize` -- read off the Config, which
        # has no such field -- was never true. `transcribe_file` now refuses a whole
        # Config outright, so that substitution cannot come back quietly.
        section = config.recimport
        if diarize is not None:
            section = dataclasses.replace(section, diarize=bool(diarize))
        result = transcribe_file(path, section, stt=config.stt)
        segments = getattr(result, "utterances", None) or []
        if getattr(result, "diarized", False) and segments:
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
                    "description": (
                        "Label each line with a speaker (needs the diarization extra). "
                        "Omit it to follow the user's [recimport] diarize setting."
                    ),
                },
            },
            "required": ["path"],
        },
        run=_run,
    )


#: The daemon caps the listening time itself (see ``[mcp] ask_human_*``); this
#: bounds how long the *client* waits for the whole exchange to come back over IPC.
_ASK_HUMAN_LISTEN_CAP_S = 120.0
#: The daemon SPEAKS the question first and only then listens (``mcp/ask.py``), and
#: transcribes afterwards. Speech runs at roughly 15 characters a second; a
#: generous estimate is better than a wait that ends mid-sentence.
_ASK_HUMAN_SPOKEN_CHARS_PER_S = 15.0
_ASK_HUMAN_SPEAK_CAP_S = 300.0
#: Transcription, the hand-back and scheduling slack.
_ASK_HUMAN_MARGIN_S = 20.0
#: ``mcp/ask.py`` prefixes the question with "<caller> asks: ".
_ASK_HUMAN_PREFIX_CHARS = 16


def ask_human_wait_s(timeout_s: object, question: str = "") -> float:
    """How long to wait on the daemon for an ``ask_human`` reply.

    The estimated time to speak the question, plus the requested listening time
    (capped at 120 s), plus a 20 s margin for transcription. The IPC client's
    default 2 s is shorter than a spoken answer, so the old call gave up while the
    user was still talking and reported a running daemon as not running; and a
    fixed small margin ended before a long question had even finished being read
    out.
    """
    try:
        listen = float(timeout_s)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        listen = 30.0
    if listen != listen or listen < 0:  # NaN or negative
        listen = 30.0
    chars = (len(question) if isinstance(question, str) else 0) + _ASK_HUMAN_PREFIX_CHARS
    speaking = min(chars / _ASK_HUMAN_SPOKEN_CHARS_PER_S, _ASK_HUMAN_SPEAK_CAP_S)
    return min(listen, _ASK_HUMAN_LISTEN_CAP_S) + speaking + _ASK_HUMAN_MARGIN_S


def _seconds(value: float | None) -> str:
    return f"{value:g} s" if value is not None else "the wait"


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
        from yazses.ipc.client import IpcTimeoutError, IpcUnreachableError
        from yazses.platform import get_platform

        platform = get_platform()
        client = platform.ipc_client_factory(platform.paths.ipc_socket)
        try:
            # `call` takes keyword params, not a dict — passing a dict makes it a
            # positional argument and raises TypeError before the socket is
            # touched. Caught by running it against the live daemon; the unit
            # tests used a fake client that accepted anything.
            reply = client.call(
                "ask_human",
                wait_s=ask_human_wait_s(timeout_s, question),
                question=question,
                timeout_s=timeout_s,
                caller="mcp",
            )
        except IpcTimeoutError as exc:
            # The daemon is there but did not answer in time: the question may
            # well have been asked (and charged to the hour's budget). Saying
            # "not running" here sent the model off to restart a healthy daemon.
            return (
                f"YazSes is running but did not reply within {_seconds(exc.timeout_s)}, so "
                "the question may or may not have been asked. Do not assume the "
                "answer is no; wait, then ask again only if you must."
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
                    "description": (
                        "The longest to wait for an answer, in seconds. Listening ends "
                        "earlier when the user stops speaking. Capped at 120 by the "
                        "daemon. The call lasts this long plus the time to speak the "
                        "question, so a large value can exceed your own client's request "
                        "timeout: keep it below that."
                    ),
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
    if stdin is None:
        _reconfigure(sys.stdin, errors="replace")
    if stdout is None:
        _reconfigure(sys.stdout, newline="\n")
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    tools = build_tools(config)

    lines = iter(source)
    while True:
        try:
            line = next(lines)
        except StopIteration:
            break
        except UnicodeDecodeError:
            # Bytes that are not UTF-8 are one bad frame, not the end of the
            # session: JSON-RPC's answer is a parse error, then carry on. (The
            # default streams are switched to ``errors="replace"`` above, so this
            # is for an injected stream that is stricter.)
            _write(sink, {"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32700, "message": "Invalid JSON."}})
            continue
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except (ValueError, RecursionError):
            # -32700 per JSON-RPC. Answered with a null id because the id lives
            # inside the frame we could not parse. A line of tens of thousands of `[`
            # raises RecursionError, which is not a ValueError; uncaught it ended
            # this loop and the client cannot restart us mid-session.
            _write(sink, {"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32700, "message": "Invalid JSON."}})
            continue

        if not isinstance(request, dict):
            _write(sink, {"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32600, "message": "Request must be an object."}})
            continue

        try:
            reply = handle(request, tools)
        except Exception as exc:  # noqa: BLE001 - one bad frame must not end the session
            # The client cannot restart this process mid-session. Fixed text on the
            # wire (nothing from the frame or the exception is reflected back) and
            # one concise line on stderr, never a traceback. A notification has no
            # id to answer, so it stays silent on stdout as the protocol requires.
            log.error("mcp: internal error handling a request (%s)", type(exc).__name__)
            reply = (
                {"jsonrpc": "2.0", "id": request["id"],
                 "error": {"code": -32603, "message": "Internal error."}}
                if request.get("id") is not None
                else None
            )
        if reply is not None:
            _write(sink, reply)
    return 0


def _reconfigure(stream: object, **settings: Any) -> None:
    """Make a default text stream UTF-8, which is what MCP's stdio transport is.

    Without this the stream uses the locale's encoding with ``errors="strict"``, so
    one invalid byte on stdin raised ``UnicodeDecodeError`` out of the read loop and
    ended a session the client cannot restart, and Windows wrote ``\r\n``. A stream
    without ``reconfigure`` (a replaced ``sys.stdin``) is left as it is.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", **settings)
    except (OSError, ValueError):
        log.debug("mcp: could not reconfigure a standard stream", exc_info=True)


def _write(sink: TextIO, payload: dict[str, Any]) -> None:
    """One frame, flushed. Without the flush a pipe buffers the reply and the
    client waits for a response that has already been written."""
    sink.write(json.dumps(payload) + "\n")
    sink.flush()
