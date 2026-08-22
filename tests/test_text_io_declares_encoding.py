"""Every text file the product reads or writes must name its encoding.

Python's default text encoding is the *locale* codepage, not UTF-8. On Linux and
macOS that is UTF-8 anyway, so a bare `read_text()` is invisible in development
and in most of CI. On Windows it is typically cp1252, and then:

* `configedit.py` -- the writer behind `yazses features`, `hotkey set` and
  `audio use` -- raises `UnicodeDecodeError` on any `config.toml` containing a
  character outside cp1252, and `UnicodeEncodeError` when asked to write one.
  **TOML is required by its specification to be UTF-8**, so this is not a
  tolerated edge case: it is reading a UTF-8 file as something else.
* the same applies to every other `config.toml` writer (`miclevel`,
  `accessibility/enroll`, `firstrun`) and to the JSON stores, JSON being UTF-8
  by specification too.

A user whose vocabulary, path or name contains an accent is enough to trigger
it, which is why this shipped for so long without being noticed on Linux.

This guard is an AST walk rather than a grep because the calls it has to catch
span several lines, and a hand-maintained list of call sites is exactly the
thing that goes stale -- the fix has to be *derived*, then proved complete.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "yazses"

#: Path methods that open a file in *text* mode and therefore pick up the locale
#: codepage when no encoding is given.
_TEXT_METHODS = {"read_text", "write_text"}


def _binary_mode(call: ast.Call) -> bool:
    """True when a builtin `open()` was asked for bytes, which needs no encoding."""
    mode = next(
        (kw.value for kw in call.keywords if kw.arg == "mode"),
        call.args[1] if len(call.args) > 1 else None,
    )
    return isinstance(mode, ast.Constant) and "b" in str(mode.value)


def _offenders() -> tuple[list[str], int, int]:
    """Return (offending "file:line:call" strings, files scanned, calls checked)."""
    bad: list[str] = []
    files = calls = 0
    for path in sorted(SRC.rglob("*.py")):
        files += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr in _TEXT_METHODS:
                name = node.func.attr
            elif isinstance(node.func, ast.Name) and node.func.id == "open":
                if _binary_mode(node):
                    continue
                name = "open"
            else:
                continue
            calls += 1
            if not any(kw.arg == "encoding" for kw in node.keywords):
                rel = path.relative_to(SRC.parents[1]).as_posix()
                bad.append(f"{rel}:{node.lineno}: {name}()")
    return bad, files, calls


def test_every_text_read_or_write_names_its_encoding() -> None:
    bad, files, calls = _offenders()

    # A guard that iterates is green over an empty collection. Prove it looked.
    assert files > 50, f"only scanned {files} source files -- the glob is wrong"
    assert calls > 20, f"only found {calls} text-IO calls -- the AST match is wrong"

    assert not bad, (
        "these read or write text using the locale codepage, which is cp1252 on "
        "Windows and corrupts or crashes on any non-ASCII content:\n  "
        + "\n  ".join(bad)
        + '\n\nPass encoding="utf-8" explicitly.'
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("p.read_text()", 1),
        ('p.read_text(encoding="utf-8")', 0),
        ("p.write_text(x)", 1),
        ('p.write_text(x, encoding="utf-8")', 0),
        ('open(p, "w")', 1),
        ('open(p, "wb")', 0),  # bytes take no encoding
        ('open(p, "w", encoding="utf-8")', 0),
        ('open(p, mode="rb")', 0),
        ("os.open(p, flags)", 0),  # not the builtin
    ],
)
def test_the_check_catches_the_shape_and_allows_the_fix(source: str, expected: int) -> None:
    """The detector itself, so a silently-broken matcher cannot pass as a clean tree."""
    found = 0
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr in _TEXT_METHODS:
            pass
        elif isinstance(node.func, ast.Name) and node.func.id == "open":
            if _binary_mode(node):
                continue
        else:
            continue
        if not any(kw.arg == "encoding" for kw in node.keywords):
            found += 1
    assert found == expected
