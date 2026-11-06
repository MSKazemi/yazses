"""Minimal JSON-RPC 2.0 framing.

Wire format: newline-delimited JSON. Each request and each response is a single
UTF-8 line terminated with '\\n'. No notifications, no batching. Errors follow
JSON-RPC 2.0 conventions but with YazSes-specific codes in the -32099..-32000
"server error" range.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

JSONRPC_VERSION = "2.0"

# Standard JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# YazSes-specific
NOT_REACHABLE = -32001  # client side — daemon socket not listening
HANDLER_FAILED = -32002  # server side — handler raised


@dataclass
class Request:
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    id: int | str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "jsonrpc": JSONRPC_VERSION,
                "method": self.method,
                "params": self.params,
                "id": self.id,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, line: str) -> Request:
        # Python's json accepts NaN/Infinity and lets 1e400 overflow to inf; neither
        # is JSON, and a non-finite value reaching a handler or the echoed id turns
        # the reply into something only Python can parse. Both leave as ValueError.
        data = json.loads(line, parse_constant=_reject_constant, parse_float=_finite_float)
        # A bare array, string, number or null is valid JSON and has no `.get`, so
        # this used to leave the method with an AttributeError. The server catches
        # (ValueError, UnicodeDecodeError) to answer with a JSON-RPC parse error, so
        # AttributeError escaped instead: the caller got a closed socket and no
        # reply, and the per-connection thread died printing a traceback into the
        # daemon log -- which reads like a crash to anyone later diagnosing a real
        # fault. Everything malformed leaves here as ValueError.
        if not isinstance(data, dict):
            raise ValueError(f"Request must be a JSON object, got {type(data).__name__}")
        if data.get("jsonrpc") != JSONRPC_VERSION:
            raise ValueError(f"Unexpected jsonrpc version: {data.get('jsonrpc')!r}")
        method = data.get("method")
        if not isinstance(method, str):
            raise ValueError("Request missing 'method' string")
        params = data.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("Request 'params' must be an object")
        request_id = data.get("id")
        if not _is_valid_id(request_id):
            # The server echoes `id` into its reply verbatim. An object, array or
            # boolean id is outside JSON-RPC 2.0 (String, Number or Null only), and a
            # non-finite one (1e400 parses to inf) was echoed as the bare token
            # `Infinity`/`NaN`: not JSON, so any non-Python caller could not parse the
            # reply it was owed. Rejected here, it gets a parse error with a null id.
            raise ValueError(f"Request 'id' must be a string, number or null, got {type(request_id).__name__}")
        return cls(method=method, params=params, id=request_id)


def _reject_constant(token: str) -> Any:
    """``json.loads`` hook: NaN, Infinity and -Infinity are not JSON (RFC 8259 §6)."""
    raise ValueError(f"Non-finite number {token} is not valid JSON")


def _finite_float(token: str) -> float:
    """``json.loads`` hook: an overflowing literal such as 1e400 would parse to inf."""
    value = float(token)
    if not math.isfinite(value):
        raise ValueError(f"Number {token} is out of range")
    return value


def _is_valid_id(value: object) -> bool:
    if value is None or isinstance(value, str):
        return True
    if isinstance(value, bool):  # bool is an int subclass; JSON true/false is not a Number
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


@dataclass
class RpcError:
    code: int
    message: str
    data: Any = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            out["data"] = self.data
        return out


@dataclass
class Response:
    id: int | str | None
    result: Any = None
    error: RpcError | None = None

    def to_json(self) -> str:
        body: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": self.id}
        if self.error is not None:
            body["error"] = self.error.to_dict()
        else:
            body["result"] = self.result
        return json.dumps(body, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> Response:
        data = json.loads(line)
        if not isinstance(data, dict):
            raise ValueError(f"Response must be a JSON object, got {type(data).__name__}")
        if data.get("jsonrpc") != JSONRPC_VERSION:
            raise ValueError(f"Unexpected jsonrpc version: {data.get('jsonrpc')!r}")
        err = data.get("error")
        rpc_error: RpcError | None = None
        if err is not None:
            # A string or list `error` has no `.get` (AttributeError) and a
            # non-numeric `code` made int() raise something else; a foreign or
            # buggy daemon can send either. Everything malformed leaves as ValueError.
            if not isinstance(err, dict):
                raise ValueError(f"Response 'error' must be an object, got {type(err).__name__}")
            try:
                code = int(err.get("code", INTERNAL_ERROR))
            except (TypeError, ValueError, OverflowError):
                # OverflowError: JSON 1e999 parses to float inf and int(inf) raises it.
                raise ValueError(f"Response error 'code' is not an integer: {err.get('code')!r}") from None
            rpc_error = RpcError(
                code=code,
                message=str(err.get("message", "")),
                data=err.get("data"),
            )
        return cls(id=data.get("id"), result=data.get("result"), error=rpc_error)
