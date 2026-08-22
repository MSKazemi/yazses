"""Text I/O must name its encoding, or Windows reads the file as cp1252.

Python's default text encoding is locale-dependent. On Linux and macOS that is
UTF-8 and every `read_text()` in this repository happens to work. On Windows it is
the ANSI code page — cp1252 — so the *same* call on the *same* file raises the
moment the file contains a character cp1252 has no room for:

    UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d in position 136742

This repo is full of such characters. Its docs use em dashes and ✓, its CLI prints
them, and its tests read both back.

It stayed invisible for a long time for a specific reason: the Windows test jobs
had been aborting during *collection* and running nothing at all. Fixing that
turned up eleven failures at once, and this was most of them — never a new
regression, just the first time anything looked.

Two shapes are checked:

* `read_text` / `write_text` / `open` in text mode with no `encoding=`;
* `str(path.relative_to(root))`, which yields `yazses\\stt\\parakeet.py` on
  Windows and matches none of the `yazses/...` keys this suite compares against.
  `.as_posix()` is identical on POSIX and correct on Windows.

To reproduce the Windows behaviour on this machine rather than trust the scan::

    uv run python -X warn_default_encoding -m pytest <files> -W error::EncodingWarning

That makes CPython raise on every text-I/O call that did not name an encoding, which
is the same set this file finds -- one is a static scan, the other an execution, and
they agree.

Scope is chosen so the guard never fires on correct code — a guard that does is a
guard someone deletes, and this one caught four false positives on its own first
run. `read_text`/`write_text` are unambiguous: only `pathlib` has them. Bare
`open(...)` is the builtin. Everything else spelled `.open(` is skipped, because
`tarfile.open`, `Image.open` and `os.open` are not text I/O at all, and
`Path.open` takes its mode as the **first** argument where the builtin takes it
second — so a mode-based check reads the wrong slot and calls `open("rb")` a
violation.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
#: `hooks/` too: it runs at commit time on whatever machine the author is using.
TREES = ("src", "tests", "scripts", "hooks")
_TEXT_IO = {"read_text", "write_text", "open"}


def _is_builtin_open(node: ast.Call) -> bool:
    """`open(...)`, not `os.open` / `tarfile.open` / `Image.open` / `Path.open`."""
    return isinstance(node.func, ast.Name) and node.func.id == "open"


def _is_binary_mode(node: ast.Call) -> bool:
    """Builtin-`open` mode argument, which is the second one."""
    return any(
        isinstance(a, ast.Constant) and isinstance(a.value, str) and "b" in a.value
        for a in node.args[1:2]
    )


def _python_files() -> list[Path]:
    return sorted(
        p for tree in TREES for p in (REPO / tree).rglob("*.py") if p.is_file()
    )


def unencoded_text_io(path: Path) -> list[tuple[int, str]]:
    """(line, call) for every text-I/O call in `path` that names no encoding."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # a fixture of deliberately broken source
        return []
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name not in _TEXT_IO:
            continue
        if any(k.arg == "encoding" for k in node.keywords):
            continue
        if name == "open" and (not _is_builtin_open(node) or _is_binary_mode(node)):
            continue
        out.append((node.lineno, name))
    return out


def stringified_relative_paths(path: Path) -> list[int]:
    """Lines using `str(x.relative_to(y))` rather than `.as_posix()`."""
    text = path.read_text(encoding="utf-8")
    return [
        i
        for i, line in enumerate(text.splitlines(), 1)
        if re.search(r"str\(\s*[A-Za-z_][A-Za-z0-9_]*\.relative_to\(", line)
    ]


# ---- the guard is not vacuous -------------------------------------------


def test_there_is_a_tree_to_check() -> None:
    """A guard that iterates is green over an empty list. If the glob breaks — a
    renamed directory, a bad path — every assertion below passes on nothing."""
    files = _python_files()
    assert len(files) > 200, f"only found {len(files)} python files; the glob is wrong"


def test_the_detector_catches_the_shapes_it_claims_to(tmp_path: Path) -> None:
    """Red-green, on source written for the purpose. Otherwise a detector that
    silently stopped matching would look exactly like a clean repository."""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "p = Path('x')\n"
        "a = p.read_text()\n"
        "b = p.write_text('y')\n"
        "c = open('f')\n"
        "d = str(p.relative_to(Path('/')))\n",
        encoding="utf-8",
    )
    assert [name for _, name in unencoded_text_io(bad)] == [
        "read_text",
        "write_text",
        "open",
    ]
    assert stringified_relative_paths(bad) == [7]


def test_the_detector_allows_the_correct_forms(tmp_path: Path) -> None:
    ok = tmp_path / "ok.py"
    ok.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "p = Path('x')\n"
        "a = p.read_text(encoding='utf-8')\n"
        "b = p.write_text('y', encoding='utf-8')\n"
        "c = open('f', encoding='utf-8')\n"
        "d = open('f', 'rb')\n"
        "e = os.open('f', os.O_RDWR)\n"
        "g = p.relative_to(Path('/')).as_posix()\n",
        encoding="utf-8",
    )
    assert unencoded_text_io(ok) == []
    assert stringified_relative_paths(ok) == []


# ---- the repository itself ----------------------------------------------


@pytest.mark.parametrize(
    "path", _python_files(), ids=lambda p: p.relative_to(REPO).as_posix()
)
def test_text_io_names_its_encoding(path: Path) -> None:
    offenders = unencoded_text_io(path)
    assert not offenders, (
        f"{path.relative_to(REPO).as_posix()} does text I/O without encoding= at "
        f"{offenders}. On Windows the default is cp1252, so this raises "
        f"UnicodeDecodeError on any file containing an em dash or a ✓ — and it "
        f"passes everywhere else."
    )


@pytest.mark.parametrize(
    "path",
    [p for p in _python_files() if p.parts[-2] == "tests" and p != Path(__file__)],
    ids=lambda p: p.relative_to(REPO).as_posix(),
)
def test_repo_relative_paths_use_as_posix(path: Path) -> None:
    """Scoped to `tests/`, which is where a repo-relative path gets *compared*
    against an `a/b/c` literal. Elsewhere it is usually going straight into a
    printed message, where a backslash is ugly and not a failure -- and flagging
    that would make this the guard nobody trusts.

    This file is exempt from itself: its red-green fixture contains the shape on
    purpose.
    """
    lines = stringified_relative_paths(path)
    assert not lines, (
        f"{path.relative_to(REPO).as_posix()} builds a repo-relative path with "
        f"str() at lines {lines}. On Windows that is backslash-separated and "
        f"matches no 'a/b/c' literal. Use .as_posix()."
    )
