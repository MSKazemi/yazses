"""Reading TOML the way people's editors actually write it.

`tomllib` rejects a leading byte-order mark. The TOML specification does not include
one, so that is defensible for a machine-generated file and wrong for every file in
this project: `config.toml`, the macros file and the style-rules file are all
hand-edited, and several ordinary Windows tools write UTF-8 **with** a BOM --
Windows PowerShell 5.1's `Set-Content` and `Out-File` do it by default, and it is
still an offered encoding in Notepad and Visual Studio.

The consequence was total rather than partial. A BOM makes the *first* line
unparseable, so the whole document fails and `load_config` falls back to defaults --
model, hotkey, VAD threshold, every setting the user had chosen -- and reports
"Invalid statement (at line 1, column 1)" about a line that looks perfectly correct
on screen. The user sees dictation behave as though they had never configured it.

So a BOM is stripped and everything else is left alone: an editor's invisible
encoding artefact is not a syntax error the user can act on, while a real syntax
error still is.

One failure is translated rather than widened. `tomllib` is a recursive-descent
parser with no depth limit of its own, so an array or inline table nested past the
interpreter's recursion limit (`x = [[[[...]]]]`, a few thousand levels) raises
`RecursionError` -- a `RuntimeError`, which none of the callers catch, so the config
loader that promises it never raises did raise. It is reported here as a
`TOMLDecodeError`, the error every caller already handles: the file is unreadable in
the same sense a syntax error makes it unreadable, and is reported the same way.
"""

from __future__ import annotations

import codecs
import tomllib
from pathlib import Path
from typing import Any

__all__ = ["NestingTooDeepError", "loads", "read"]

_NESTING_MESSAGE = "a value is nested too deeply to parse"


class NestingTooDeepError(tomllib.TOMLDecodeError):
    """`tomllib` ran out of recursion depth. A `TOMLDecodeError`, so callers need no change.

    Built through `ValueError.__init__` with a single message: `(msg, doc, pos)` is the
    3.14 signature of `TOMLDecodeError`, and on 3.11-3.13 the same three arguments would
    make `str(exc)` a tuple carrying the whole document into a log line or `doctor`.
    """

    def __init__(self) -> None:
        ValueError.__init__(self, _NESTING_MESSAGE)


def _parse(text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except RecursionError:
        # Caught after the parser's own frames have unwound, so the stack has room
        # again. `from None`: the thousand-frame chain names nothing a user can act on.
        raise NestingTooDeepError() from None


def loads(text: str) -> dict[str, Any]:
    """Parse TOML text, tolerating a leading BOM."""
    return _parse(text.lstrip("﻿"))


def read(path: str | Path) -> dict[str, Any]:
    """Parse the TOML document at *path*, tolerating a UTF-8 BOM.

    Raises what `tomllib.load` raises, so every existing caller's error handling
    still applies -- this widens what parses, never what is reported.
    """
    data = Path(path).read_bytes()
    if data.startswith(codecs.BOM_UTF8):
        data = data[len(codecs.BOM_UTF8):]
    # `decode` here rather than handing bytes to `tomllib.load`: a file that is not
    # valid UTF-8 must still raise, and `UnicodeDecodeError` is a `ValueError`, which
    # is what the callers already catch alongside `TOMLDecodeError`.
    return _parse(data.decode("utf-8"))
