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

import pytest

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


def test_an_unknown_tool_is_a_protocol_error() -> None:
    """MCP distinguishes the two, and clients rely on it: a protocol error means
    the *call* was malformed (2025-06-18 "Tools / Error Handling": "Unknown tools",
    code -32602), while a failed tool is a normal result the model can read and
    react to. This used to be an `isError` result."""
    reply = handle(_req("tools/call", {"name": "nope", "arguments": {}}), TOOLS)
    assert "result" not in reply
    assert reply["error"]["code"] == -32602
    assert "transcribe" in reply["error"]["message"], "names what is offered"
    assert "nope" not in reply["error"]["message"], "the caller's value is not reflected"


def test_a_tool_that_raises_becomes_an_error_result_not_a_crash() -> None:
    """One bad call must not take the server down: it is a long-lived stdio
    process, and the client has no way to restart it mid-session."""
    def _boom(**kwargs):
        raise RuntimeError("no such file")

    tools = (ToolSpec(name="boom", description="", schema={}, run=_boom),)
    reply = handle(_req("tools/call", {"name": "boom", "arguments": {}}), tools)
    assert reply["result"]["isError"] is True
    # A stable public message per failure class; the exception text stays server-side.
    assert "no such file" not in reply["result"]["content"][0]["text"]
    assert reply["result"]["content"][0]["text"].startswith("boom failed:")


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
    """"No tool named None" reads as though None were a name that was tried. A
    missing name is a malformed call: a protocol error, not a tool result."""
    reply = _call([_Tool()], arguments={})
    text = reply["error"]["message"]
    assert reply["error"]["code"] == -32602
    assert "needs a string 'name'" in text, text
    assert "None" not in text, f"Python's None leaked into the message: {text}"


@pytest.mark.parametrize("name", [1, True, [], {}, ""], ids=repr)
def test_a_non_string_tool_name_is_a_protocol_error(name):
    assert _call([_Tool()], name=name)["error"]["code"] == -32602


def test_an_unknown_tool_still_lists_what_is_offered():
    reply = _call([_Tool()], name="nope", arguments={})
    text = reply["error"]["message"]
    assert reply["error"]["code"] == -32602
    assert "Unknown tool" in text and "transcribe" in text


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
    assert reply["result"]["content"][0]["text"].startswith("transcribe failed:")


# ---- a non-object `params` is answered, not raised ----------------------------

_NOT_AN_OBJECT = ["x", 1, True, [1], [], 0, "", False]


@pytest.mark.parametrize("method", ["initialize", "tools/call"])
@pytest.mark.parametrize("params", _NOT_AN_OBJECT, ids=repr)
def test_a_non_object_params_is_invalid_params_not_a_crash(method, params):
    """`"params": "x"` used to raise AttributeError out of `handle()` and end the
    stdio process. JSON-RPC's answer is -32602 with the request id echoed, and the
    message is fixed text so a client's input is never reflected back."""
    reply = handle({"jsonrpc": "2.0", "id": 9, "method": method, "params": params}, TOOLS)

    assert reply["id"] == 9
    assert reply["error"]["code"] == -32602
    assert reply["error"]["message"] == "Invalid params: params must be an object."
    assert "result" not in reply


@pytest.mark.parametrize("method", ["initialize", "tools/call"])
def test_the_invalid_params_message_does_not_echo_the_input(method):
    reply = handle(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": "SECRET-TOKEN-123"}, TOOLS
    )
    assert "SECRET-TOKEN-123" not in repr(reply)


@pytest.mark.parametrize("method", ["initialize", "tools/call", "tools/list"])
def test_a_non_object_params_on_a_notification_is_still_unanswered(method):
    assert handle({"jsonrpc": "2.0", "method": method, "params": "x"}, TOOLS) is None


def test_absent_or_null_params_are_still_accepted_for_initialize():
    """Both are an ordinary way to say "no parameters"; only a present value of the
    wrong type is an error."""
    for request in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": None},
    ):
        reply = handle(request, TOOLS)
        assert reply["result"]["serverInfo"]["name"] == "yazses"


def test_tools_call_without_params_still_names_the_missing_field():
    reply = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call"}, TOOLS)
    assert reply["error"]["code"] == -32602
    assert "needs a string 'name'" in reply["error"]["message"]


def test_a_large_valid_call_is_unchanged():
    big = "a" * 1_000_000
    reply = _call([_Tool()], name="transcribe", arguments={"path": big})
    assert not reply["result"].get("isError")
    assert big in reply["result"]["content"][0]["text"]


# ---- ping (2025-06-18 basic/utilities/ping) ------------------------------------


@pytest.mark.parametrize("rid", [1, "p", 0])
def test_ping_is_answered_with_an_empty_result(rid):
    """"The receiver MUST respond promptly with an empty response". It used to be
    -32601 Unknown method, which a client that pings for liveness reads as a dead
    server."""
    assert handle(_req("ping", rid=rid), TOOLS) == {"jsonrpc": "2.0", "id": rid, "result": {}}


def test_ping_with_odd_params_is_still_answered():
    assert handle(_req("ping", {"x": 1}), TOOLS)["result"] == {}


def test_a_ping_notification_gets_no_reply():
    assert handle({"jsonrpc": "2.0", "method": "ping"}, TOOLS) is None


# ---- version negotiation (2025-06-18 basic/lifecycle) --------------------------


@pytest.mark.parametrize("asked", ["2025-06-18", "2025-03-26", "2024-11-05"])
def test_a_supported_version_is_echoed(asked):
    got = handle(_req("initialize", {"protocolVersion": asked}), TOOLS)
    assert got["result"]["protocolVersion"] == asked


@pytest.mark.parametrize("asked", ["1999-01-01", 5, {"a": 1}, ["x"], "garbage", None, "", True],
                         ids=repr)
def test_an_unsupported_version_is_answered_with_the_latest_supported(asked):
    """"Otherwise, the server MUST respond with another protocol version it
    supports. This SHOULD be the latest version supported by the server." It used
    to echo whatever the client sent -- a number, a list -- back as the version."""
    got = handle(_req("initialize", {"protocolVersion": asked}), TOOLS)["result"]["protocolVersion"]
    assert got == "2025-06-18"


# ---- tools/call: arguments are checked against the published schema ------------


class _Flag:
    name = "flag"
    description = ""
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "diarize": {"type": "boolean"},
            "n": {"type": "integer"},
            "t": {"type": "number"},
        },
        "required": ["path"],
    }
    seen: list = []

    @classmethod
    def run(cls, path, diarize=None, n=None, t=None):
        cls.seen.append((path, diarize, n, t))
        return "ran"


@pytest.mark.parametrize(
    "arguments",
    [
        {"path": "a", "diarize": "false"},
        {"path": "a", "diarize": 0},
        {"path": "a", "diarize": "true"},
        {"path": 5},
        {"path": "a", "n": 1.5},
        {"path": "a", "n": True},
        {"path": "a", "t": "3"},
        {"path": "a", "t": False},
        {"path": None},
    ],
    ids=repr,
)
def test_a_mistyped_argument_is_refused_before_the_tool_runs(arguments):
    """The string "false" is truthy in Python: `bool("false")` turned diarization ON
    for a caller that asked for it OFF. The schema says boolean, so the call is
    refused -- as a result the model can read and retry, naming the field."""
    _Flag.seen.clear()
    reply = _call([_Flag()], name="flag", arguments=arguments)
    assert reply["result"]["isError"] is True
    assert "invalid arguments" in reply["result"]["content"][0]["text"]
    assert _Flag.seen == [], "the tool must not run on a mistyped call"


def test_correctly_typed_arguments_run_and_null_means_omitted():
    _Flag.seen.clear()
    ok = _call([_Flag()], name="flag",
               arguments={"path": "a", "diarize": False, "n": 2, "t": 1.5})
    nulls = _call([_Flag()], name="flag", arguments={"path": "a", "diarize": None})
    assert not ok["result"].get("isError") and not nulls["result"].get("isError")
    assert _Flag.seen == [("a", False, 2, 1.5), ("a", None, None, None)]


def test_an_int_is_a_valid_number():
    _Flag.seen.clear()
    assert not _call([_Flag()], name="flag", arguments={"path": "a", "t": 3})["result"].get("isError")


@pytest.mark.parametrize("arguments", ["x", [1], 5, True], ids=repr)
def test_non_object_arguments_are_invalid_params(arguments):
    reply = _call([_Flag()], name="flag", arguments=arguments)
    assert reply["error"]["code"] == -32602


def test_an_unexpected_argument_name_is_not_reflected():
    reply = _call([_Flag()], name="flag", arguments={"path": "a", "SECRET-NAME": 1})
    text = reply["result"]["content"][0]["text"]
    assert reply["result"]["isError"] is True
    assert "SECRET-NAME" not in text and "Accepts: path" in text


# ---- a failing tool does not leak its exception text ---------------------------

SENTINEL = "/home/someone/SENTINEL-TOKEN-7731/credentials.json"


@pytest.mark.parametrize(
    "exc, fragment",
    [
        (FileNotFoundError(SENTINEL), "not found"),
        (PermissionError(SENTINEL), "permission"),
        (OSError(SENTINEL), "I/O"),
        (ValueError(SENTINEL), "could not be processed"),
        (ImportError(SENTINEL), "not installed"),
        (RuntimeError(SENTINEL), "unexpectedly"),
        (KeyError(SENTINEL), "unexpectedly"),
        (TypeError(SENTINEL), "unexpectedly"),
    ],
    ids=lambda v: type(v).__name__ if isinstance(v, BaseException) else v,
)
def test_a_tool_failure_gets_a_stable_public_message(exc, fragment, capfd, caplog):
    """The raw `ExcName: message` used to reach the client, so a path or token inside
    an exception was disclosed to whatever agent called the tool. The wire carries a
    fixed sentence per failure class; the exception goes to stderr, never stdout."""
    def _boom(**kwargs):
        raise exc

    tools = (ToolSpec(name="boom", description="", schema={}, run=_boom),)
    reply = handle(_req("tools/call", {"name": "boom", "arguments": {}}), tools)

    wire = repr(reply)
    assert reply["result"]["isError"] is True
    assert "SENTINEL-TOKEN-7731" not in wire
    assert type(exc).__name__ not in wire
    assert fragment in reply["result"]["content"][0]["text"]
    captured = capfd.readouterr()
    assert captured.out == "", "stdout carries the protocol and nothing else"
    # Logged, not printed: the logging system's destination is stderr (see the
    # subprocess test in test_mcp_server.py for the unconfigured, real-process case).
    assert "SENTINEL-TOKEN-7731" in caplog.text, "the full exception is logged"


# ---- exceptions written for users keep their cause and fix --------------------


def _failure(exc: BaseException) -> str:
    def _boom(**kwargs):
        raise exc

    tools = (ToolSpec(name="transcribe", description="", schema={}, run=_boom),)
    reply = handle(_req("tools/call", {"name": "transcribe", "arguments": {}}), tools)
    assert reply["result"]["isError"] is True
    return reply["result"]["content"][0]["text"]


def test_a_missing_speech_model_tells_the_agent_what_to_do():
    """On origin/main the client was told the cause and the fix; the first version of
    the stable mapper reduced it to "the tool failed unexpectedly", and MCP clients
    mostly do not show stderr to the model, so nobody could say what to run."""
    from yazses.stt.errors import ModelUnavailableError

    text = _failure(ModelUnavailableError("base.en", f"offline: {SENTINEL}"))

    assert "model 'base.en' is not on this machine" in text
    assert "yazses model download base.en" in text and "yazses restart" in text


def test_only_the_first_line_of_a_model_error_is_exposed():
    """The exception's full text holds the underlying cause and the cache directory
    (`Cause: ...`, `into: <hub cache>`): a path and whatever the library printed."""
    from yazses.stt.errors import ModelUnavailableError

    text = _failure(ModelUnavailableError("base.en", f"offline: {SENTINEL}"))

    assert "SENTINEL-TOKEN-7731" not in text
    assert "Cause" not in text and "into:" not in text and "\n" not in text


def test_a_model_name_that_is_a_local_path_is_not_repeated():
    from yazses.stt.errors import ModelUnavailableError

    text = _failure(ModelUnavailableError("/home/someone/SENTINEL-TOKEN-7731/model", "x"))

    assert "SENTINEL-TOKEN-7731" not in text and "/home" not in text
    assert text.startswith("transcribe failed:") and "yazses doctor" in text


@pytest.mark.parametrize(
    "build, fix",
    [
        (lambda: __import__("yazses.stt.errors", fromlist=["x"]).ComputeTypeUnsupportedError(
            "base.en", "float16", "cpu", SENTINEL), "Remove the compute_type line"),
        (lambda: __import__("yazses.stt.errors", fromlist=["x"]).DeviceUnavailableError(
            "base.en", "cuda", SENTINEL), 'device = "cpu"'),
        (lambda: __import__("yazses.stt.errors", fromlist=["x"]).LanguageUnsupportedError(
            "faster-whisper", "base.en", "fa", SENTINEL), "yazses language status"),
        (lambda: __import__("yazses.stt.errors", fromlist=["x"]).LanguageUnsupportedError(
            "faster-whisper", "base.en", "fa", SENTINEL,
            requested_engine="parakeet", requested_failure=SENTINEL), "yazses language status"),
    ],
    ids=["compute-type", "device", "language", "language-with-fallback"],
)
def test_every_speech_model_error_class_gives_a_fix_and_no_sentinel(build, fix):
    text = _failure(build())

    assert fix in text, text
    assert "SENTINEL-TOKEN-7731" not in text
    assert "\n" not in text and "Cause" not in text


def test_a_lookalike_exception_does_not_opt_in():
    """Only the speech-model classes are written to be shown; an ordinary RuntimeError
    whose text reads like a sentence is not."""
    text = _failure(RuntimeError(f"The speech-to-text model is not here: {SENTINEL}"))

    assert "SENTINEL-TOKEN-7731" not in text and "unexpectedly" in text


# ---- a missing optional component is named, without a path --------------------


def test_a_missing_module_is_named():
    text = _failure(ModuleNotFoundError(f"No module named 'sherpa_onnx' ({SENTINEL})",
                                        name="sherpa_onnx"))

    assert text == "transcribe failed: a component this tool needs is not installed: sherpa_onnx."


def test_only_the_top_level_module_is_named():
    text = _failure(ModuleNotFoundError("x", name="pyannote.audio.pipelines"))
    assert text == "transcribe failed: a component this tool needs is not installed: pyannote."


@pytest.mark.parametrize(
    "name", ["/home/someone/SENTINEL-TOKEN-7731/mod", "a b", "x;rm -rf", "C:\\SENTINEL-TOKEN-7731", "", None],
    ids=repr,
)
def test_a_module_name_that_is_not_an_identifier_is_not_repeated(name):
    text = _failure(ModuleNotFoundError(f"No module named {SENTINEL}", name=name))

    assert "SENTINEL-TOKEN-7731" not in text and "rm -rf" not in text
    assert "not installed" in text and "installed:" not in text


def test_an_import_error_that_is_not_a_missing_module_stays_generic():
    text = _failure(ImportError(f"cannot import name 'x' from {SENTINEL}", name="/p/SENTINEL"))

    assert "SENTINEL" not in text and "not installed" in text and "installed:" not in text


# ---- JSON numbers: 5.0 is an integer ------------------------------------------


@pytest.mark.parametrize("value", [5, 5.0, 0.0, -3.0, 1e3])
def test_an_integral_float_is_a_valid_integer(value):
    _Flag.seen.clear()
    reply = _call([_Flag()], name="flag", arguments={"path": "a", "n": value})
    assert not reply["result"].get("isError"), reply
    assert _Flag.seen[0][2] == value


@pytest.mark.parametrize("value", [5.5, float("inf"), float("nan"), True, False, "5"], ids=repr)
def test_a_non_integral_value_is_still_not_an_integer(value):
    _Flag.seen.clear()
    reply = _call([_Flag()], name="flag", arguments={"path": "a", "n": value})
    assert reply["result"]["isError"] is True and _Flag.seen == []
