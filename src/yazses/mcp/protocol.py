"""MCP request → response, with no I/O in sight (ADR-020 §1).

MCP is JSON-RPC 2.0 over stdio and this server answers
``initialize``, ``tools/list``, ``tools/call`` and ``ping``. Hand-written rather than taken
from an SDK — the surface is three methods, `ipc/protocol.py` already sets this
project's JSON-RPC conventions, and ADR-016's dependency budget makes a library
for that a poor trade. ADR-020 anticipated the question and left FastMCP as "an
implementation detail governed by ADR-016 like any other dependency".

The split that matters here is MCP's own, and clients depend on it:

* a **JSON-RPC error** means the call itself was wrong — unknown method,
  malformed frame, unknown tool. The client has a bug (2025-06-18 "Tools",
  "Error Handling": "Protocol Errors ... Unknown tools" is ``-32602``).
* a **result with ``isError``** means the tool ran and failed. That is ordinary
  content the model can read and react to, not a transport failure.

Getting those the wrong way round makes a missing file look like a broken server.
"""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from yazses.ipc.protocol import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    JSONRPC_VERSION,
    METHOD_NOT_FOUND,
)

#: What this server implements. A client that asks for another revision is
#: answered in its own — it cannot downgrade after the handshake, and the three
#: methods here have been stable across revisions.
PROTOCOL_VERSION = "2025-06-18"

#: Revisions this server will speak. 2025-06-18 "Lifecycle / Version Negotiation":
#: if the server supports the requested version it MUST answer with the same one,
#: "otherwise ... another protocol version it supports", which SHOULD be its latest.
#: Echoing an arbitrary client string (a number, a list, "1999-01-01") answered
#: with a revision this server has never heard of.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

log = logging.getLogger(__name__)

SERVER_INFO = {"name": "yazses", "title": "YazSes"}


def _server_info() -> dict[str, str]:
    """`serverInfo` for the initialize result.

    MCP's `Implementation` requires `version` next to `name`; Claude Code validates it
    and refuses to connect without one. Read from the installed package metadata on
    each initialize (once per session), so the number cannot drift from the release.
    """
    from yazses import __version__

    return {**SERVER_INFO, "version": __version__}


#: Fixed text: a client's malformed value is never reflected back in the error.
_INVALID_PARAMS_MESSAGE = "Invalid params: params must be an object."


@dataclass(frozen=True)
class ToolSpec:
    """One exposed tool: what it is called, what it takes, and what runs it."""

    name: str
    description: str
    schema: dict[str, Any]
    run: Callable[..., Any]


#: Public text for a tool that ran and failed, by failure class. The first match
#: wins, so the narrow classes come before their bases. Nothing from the exception
#: -- its message, a path inside it, a token -- is put on the wire: the full
#: exception goes to stderr (see ``handle``). A message the model needs in order to
#: retry correctly (a wrong argument) is built from the tool's own schema instead.
_FAILURE_MESSAGES: tuple[tuple[type[BaseException], str], ...] = (
    (FileNotFoundError, "the file was not found."),
    (PermissionError, "permission was denied."),
    (IsADirectoryError, "the path is a directory, not a file."),
    (NotADirectoryError, "part of the path is not a directory."),
    (TimeoutError, "the operation timed out."),
    (ImportError, "a component this tool needs is not installed."),
    (MemoryError, "the machine ran out of memory."),
    (OSError, "the operating system reported an I/O error."),
    (ValueError, "the input could not be processed."),
)
_GENERIC_FAILURE = "the tool failed unexpectedly. Details are in the server's log."

#: JSON Schema primitive types a tool's ``inputSchema`` here may declare.
_SCHEMA_TYPES: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    # JSON has one number type: `5.0` is an integer to JSON Schema, and json.loads
    # hands it over as a float.
    "integer": lambda v: (isinstance(v, int) and not isinstance(v, bool))
    or (isinstance(v, float) and v.is_integer()),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


#: A Python identifier, which is all of a module's name this server will repeat.
_PLAIN_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")

#: Text that looks like it holds a filesystem path. A line that matches is never
#: repeated, whatever class raised it: an absolute path, a drive, a UNC share, a
#: home reference, or two path separators in one line.
_PATHISH = re.compile(r"""(^|[\s'"(=])/|[A-Za-z]:[\\/]|\\|~[\\/]""")
_MAX_PUBLIC_LINE = 240

#: The commands a fix sentence names ("yazses model", "yazses restart"). A first line
#: that already holds all of them carries the fix and is not followed by it again.
#: Lower-case on purpose: the product name in prose is "YazSes".
_COMMAND = re.compile(r"\byazses [a-z]+\b")


def _pathish(line: str) -> bool:
    return bool(_PATHISH.search(line)) or line.count("/") >= 2


def _first_line_if_safe(exc: BaseException) -> str | None:
    """The first line of ``str(exc)`` -- only when it is short and path-free."""
    first = next((ln.strip() for ln in str(exc).splitlines() if ln.strip()), "")
    if not first or len(first) > _MAX_PUBLIC_LINE or _pathish(first):
        return None
    return first


def _speech_model_message(exc: BaseException) -> str | None:
    """The cause and the fix for the speech-model errors, which are written for users.

    ``stt/errors.py`` builds these as a cause on the first line, the long
    explanation below it (including the cache directory and the underlying
    exception), and the fix near the end. Only the first line is repeated here,
    and only when it holds no path; the fix is a fixed sentence per class, because
    on the wire the first line alone says what is wrong and not what to do -- and
    a client that cannot show stderr to the model leaves the user with a
    meaningless "the tool failed". The ``model`` attribute is repeated only when it
    is a plain model name and not a local path.
    """
    try:
        from yazses.stt import errors as stt_errors
    except Exception:  # noqa: BLE001 - an optional nicety must never become a failure
        return None

    # The most specific class first: every one below is a ModelUnavailableError.
    if isinstance(exc, stt_errors.LanguageUnsupportedError):
        if getattr(exc, "requested_engine", ""):
            return (
                "the configured speech engine is not running and the selected language "
                "needs it. Run: yazses language status, then: yazses restart."
            )
        fallback = "the language, engine and model in [stt] do not agree."
        fix = "Run: yazses language status, then: yazses restart."
    elif isinstance(exc, stt_errors.DeviceUnavailableError):
        fallback = "the speech model could not start on the configured device."
        fix = 'Set device = "cpu" under [stt] in config.toml, then: yazses restart.'
    elif isinstance(exc, stt_errors.ComputeTypeUnsupportedError):
        fallback = "the configured compute type is not supported on this machine."
        fix = "Remove the compute_type line from [stt] in config.toml, then: yazses restart."
    elif isinstance(exc, stt_errors.ModelUnavailableError):
        fallback = "the speech-to-text model is not on this machine."
        model = getattr(exc, "model", "")
        if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9._-]+)?", model):
            fix = f"Run: yazses model download {model}, then: yazses restart."
        else:
            fix = "Run: yazses doctor."
    else:
        return None
    first = _first_line_if_safe(exc)
    if first is not None and all(c in first for c in _COMMAND.findall(fix)):
        return first  # cause and fix already on the line: say neither twice
    return f"{first or fallback} {fix}"


def _failure_text(name: str, exc: BaseException) -> str:
    # Opt-in public messages: exceptions whose text is a cause and a fix by design.
    public = _speech_model_message(exc)
    if public is not None:
        return f"{name} failed: {public}"
    if isinstance(exc, ModuleNotFoundError):
        # Name the missing optional component, and only a plain module name: the
        # exception's text can carry a path, its `name` attribute is the module.
        top = (exc.name or "").split(".")[0]
        if _PLAIN_IDENTIFIER.fullmatch(top):
            return f"{name} failed: a component this tool needs is not installed: {top}."
    for kind, message in _FAILURE_MESSAGES:
        if isinstance(exc, kind):
            return f"{name} failed: {message}"
    return f"{name} failed: {_GENERIC_FAILURE}"


def _argument_problem(tool: ToolSpec, arguments: dict[str, Any]) -> str | None:
    """Why *arguments* cannot be passed to *tool*, or ``None`` when they can.

    Answered from the tool's published ``inputSchema`` (what ``tools/list``
    shows), and only ever with names from that schema -- never the caller's
    values. Missing and unknown arguments are found by binding against the
    callable, so a wrong list is explained instead of tracebacked; types are
    checked against the schema, so the string ``"false"`` can no longer turn a
    boolean on.
    """
    schema = tool.schema or {}
    properties = schema.get("properties") or {}
    required = list(schema.get("required") or [])
    problems: list[str] = []

    try:
        inspect.signature(tool.run).bind(**arguments)
    except TypeError:
        missing = [n for n in required if n not in arguments]
        unknown = [n for n in arguments if n not in properties] if properties else []
        if missing:
            problems.append("missing: " + ", ".join(missing))
        if unknown:
            problems.append(f"{len(unknown)} argument(s) not in the schema")
        if not problems:
            problems.append("the arguments do not fit this tool")
    else:
        for arg, value in arguments.items():
            declared = (properties.get(arg) or {}).get("type")
            check = _SCHEMA_TYPES.get(declared) if isinstance(declared, str) else None
            if check is not None and not check(value):
                problems.append(f"'{arg}' must be a {declared}")

    if not problems:
        return None
    return (
        f"{tool.name}: invalid arguments ({'; '.join(problems)}). "
        f"Required: {', '.join(required) or 'none'}. "
        f"Accepts: {', '.join(properties) or 'none'}."
    )


def _text(body: str, *, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": body}]}
    if is_error:
        result["isError"] = True
    return result


def _error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": rid, "error": {"code": code, "message": message}}


def _ok(rid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": rid, "result": result}


def _params_of(request: dict[str, Any]) -> dict[str, Any] | None:
    """The request's ``params`` as an object, or ``None`` when it is not one.

    Absent and ``null`` both mean "no parameters" and give ``{}``. Any other
    non-object value (``"x"``, ``1``, ``[1]``, ``[]``) is the caller's bug.
    """
    raw = request.get("params")
    if raw is None:
        return {}
    return raw if isinstance(raw, dict) else None


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

    if method == "ping":
        # 2025-06-18 "Ping": "The receiver MUST respond promptly with an empty
        # response" -- `result: {}`, whatever the params and the session state.
        return _ok(rid, {})

    if method == "initialize":
        params = _params_of(request)
        if params is None:
            return _error(rid, INVALID_PARAMS, _INVALID_PARAMS_MESSAGE)
        asked = params.get("protocolVersion")
        return _ok(rid, {
            # The client's revision when this server speaks it (a client cannot
            # downgrade after the handshake), otherwise the latest this server
            # supports -- never an arbitrary echoed value.
            "protocolVersion": (
                asked
                if isinstance(asked, str) and asked in SUPPORTED_PROTOCOL_VERSIONS
                else PROTOCOL_VERSION
            ),
            "capabilities": {"tools": {}},
            "serverInfo": _server_info(),
        })

    if method == "tools/list":
        return _ok(rid, {"tools": [
            {"name": t.name, "description": t.description, "inputSchema": t.schema}
            for t in tools
        ]})

    if method == "tools/call":
        params = _params_of(request)
        if params is None:
            return _error(rid, INVALID_PARAMS, _INVALID_PARAMS_MESSAGE)
        name = params.get("name")
        offered = ", ".join(t.name for t in tools) or "none"
        if not isinstance(name, str) or not name:
            # Protocol errors (2025-06-18 "Tools / Error Handling": unknown tools
            # are -32602), with fixed text: the caller's value is not reflected.
            return _error(
                rid, INVALID_PARAMS,
                f"tools/call needs a string 'name'. This server offers: {offered}.",
            )
        chosen = next((t for t in tools if t.name == name), None)
        if chosen is None:
            return _error(rid, INVALID_PARAMS, f"Unknown tool. This server offers: {offered}.")

        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return _error(rid, INVALID_PARAMS, "Invalid params: arguments must be an object.")
        # `null` for an optional argument means "not given". A required one set to
        # null is still wrong and is reported as such below.
        required = set((chosen.schema or {}).get("required") or [])
        arguments = {k: v for k, v in arguments.items() if v is not None or k in required}

        # Check before calling, so a wrong argument list is answered from the
        # tool's own schema instead of by Python. Calling straight through
        # reported
        #
        #   TypeError: transcribe_tool.<locals>._run() missing 1 required
        #   positional argument: 'path'
        #
        # to the model on the other end -- an internal closure name and a traceback
        # string, from which it has to guess the parameter it left out. The schema
        # is already published by tools/list; this answers from the same source.
        # It stays an `isError` result, not a JSON-RPC error: the model can read it
        # and retry, and the spec lists both "invalid arguments" (protocol) and
        # "invalid input data" (execution) -- this is an owner-visible choice.
        problem = _argument_problem(chosen, arguments)
        if problem is not None:
            return _ok(rid, _text(problem, is_error=True))

        try:
            outcome = chosen.run(**arguments)
        except Exception as exc:  # noqa: BLE001 - a failed tool is a result, not a crash
            # Never propagate: this is a long-lived stdio process and the client
            # cannot restart it mid-session, so one bad argument must not end it.
            # The wire gets a stable message per failure class; the exception
            # itself -- which can carry a path or a token -- goes to stderr only
            # (stdout carries the protocol and nothing else).
            log.error("mcp: tool %r failed", chosen.name, exc_info=exc)
            return _ok(rid, _text(_failure_text(chosen.name, exc), is_error=True))
        return _ok(rid, _text(outcome if isinstance(outcome, str) else repr(outcome)))

    return _error(rid, METHOD_NOT_FOUND, f"Unknown method: {method!r}")
