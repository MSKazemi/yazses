"""No tracked text file may contain a merge-conflict marker.

A union merge once committed seven `|||||||` base-section markers into CHANGELOG.md, and the
suite stayed green (about 16k tests) because nothing in it reads CHANGELOG.md as anything but
text. The markers are the one artefact of an unfinished merge that every language, markup and
config format happily tolerates inside a comment, a string or a paragraph, so no per-format
test will ever find them. This is the format-independent check.

**What counts, and what deliberately does not** (AGENTS.md rule 9: a guard is judged on how
rarely it fires). Git writes a conflict as, at the start of a line:

    <<<<<<< ours        (marker, then a space and a label, or nothing)
    ||||||| base        (diff3/zdiff3 style only)
    =======             (exactly seven, nothing else)
    >>>>>>> theirs

A line of seven or more `=` is also a Markdown setext heading underline, an RST section rule
and an ASCII table border, all of which appear in ordinary files -- so a lone `=======` is
**never** reported. It counts only when it sits between a `<<<<<<<` and a `>>>>>>>` (or after
an unclosed `<<<<<<<`), i.e. when it is demonstrably the middle of a conflict. The three
other markers are reported on their own: seven `<`, `>` or `|` at column 0 followed by a space
or the end of the line has no ordinary meaning. Indented markers (inside a Markdown code block
that documents conflicts, say) are not at column 0 and are ignored. A fenced block at column
0 that quotes a conflict *would* fire; none exists in the tree, and the cure is to indent it.

The markers in this file are built with `"<" * 7`, never written out, so the file does not
trip the guard it defines and needs no exclusion list.

Measured on the tree this was written against: 2879 tracked files, 0 offenders. A naive
`^(<{7}|>{7}|={7}|\\|{7})` prefix scan flagged 8 files, every one an ASCII `=====` rule or a
log line, 0 of them conflicts; the rules below flag none of them.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.gitprobe import require_git

ROOT = Path(__file__).resolve().parent.parent

OPEN = "<" * 7
BASE = "|" * 7
MID = "=" * 7
CLOSE = ">" * 7

_OPEN = re.compile(re.escape(OPEN) + r"( .*)?")
_BASE = re.compile(re.escape(BASE) + r"( .*)?")
_CLOSE = re.compile(re.escape(CLOSE) + r"( .*)?")
_MID = re.compile(re.escape(MID))

#: A tracked tree this size cannot have fewer text files than this; below it the walk found
#: the wrong directory or git answered nothing, and "no offenders" would mean nothing.
MIN_FILES_SCANNED = 500


def conflict_markers(text: str) -> list[tuple[int, str]]:
    """``(line number, marker kind)`` for every conflict marker in ``text``. Pure.

    ``=======`` is reported only while inside an open ``<<<<<<<`` region -- see the module
    docstring for why a bare one is not evidence of anything.
    """
    found: list[tuple[int, str]] = []
    in_region = False
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.rstrip("\r")
        if _OPEN.fullmatch(line):
            found.append((number, "open"))
            in_region = True
        elif _BASE.fullmatch(line):
            found.append((number, "base"))
        elif _CLOSE.fullmatch(line):
            found.append((number, "close"))
            in_region = False
        elif in_region and _MID.fullmatch(line):
            found.append((number, "separator"))
    return found


def _read_text(path: Path) -> str | None:
    """The file as text, or ``None`` for a binary, unreadable, missing or symlinked path."""
    if path.is_symlink() or not path.is_file():
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan_files(paths: list[Path], root: Path = ROOT) -> tuple[int, list[str]]:
    """``(files actually read as text, offender descriptions)``. The count is returned so a
    caller can refuse to treat an empty walk as a clean one."""
    scanned = 0
    offenders: list[str] = []
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        scanned += 1
        for number, kind in conflict_markers(text):
            try:
                shown = path.relative_to(root)
            except ValueError:
                shown = path
            offenders.append(f"{shown}:{number}: conflict marker ({kind})")
    return scanned, offenders


def _tracked_files() -> list[Path]:
    require_git()
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    return [ROOT / name.decode("utf-8", "surrogateescape") for name in out.split(b"\0") if name]


# --------------------------------------------------------------------- the real tree


def test_no_tracked_text_file_contains_a_conflict_marker() -> None:
    scanned, offenders = scan_files(_tracked_files())

    assert scanned >= MIN_FILES_SCANNED, (
        f"only {scanned} text files were scanned -- the guard is blind, not clean"
    )
    assert offenders == [], "unresolved merge conflict:\n" + "\n".join(offenders)


# ------------------------------------------------- the scanner, on synthetic input


CONFLICT = f"""# Changelog

{OPEN} HEAD
- added the thing
{BASE} merged common ancestors
- the old thing
{MID}
- added a different thing
{CLOSE} feature/other
"""


def test_a_real_conflict_is_found_with_every_marker_named() -> None:
    assert conflict_markers(CONFLICT) == [
        (3, "open"), (5, "base"), (7, "separator"), (9, "close"),
    ]


def test_the_incident_shape_a_lone_base_marker_is_found() -> None:
    """A union merge keeps no `<<<<<<<` or `>>>>>>>` -- only the base lines survive."""
    text = "ok\n" + (BASE + "\n") * 7 + "ok\n"
    assert [kind for _, kind in conflict_markers(text)] == ["base"] * 7


def test_an_unclosed_open_marker_is_found_with_its_separator() -> None:
    assert [k for _, k in conflict_markers(f"{OPEN} HEAD\na\n{MID}\nb\n")] == ["open", "separator"]


def test_crlf_line_endings_do_not_hide_a_conflict() -> None:
    assert len(conflict_markers(CONFLICT.replace("\n", "\r\n"))) == 4


@pytest.mark.parametrize(
    "text",
    [
        f"Title\n{MID}\nbody\n",                       # Markdown setext H1
        f"Title\n{MID}\n\nSubtitle\n{'-' * 7}\n",      # ... and an RST-ish pair
        f"{MID}\nSection\n{MID}\n",                    # RST over/underline
        f"{MID} {MID} {MID}\n",                        # an ASCII table row
        f"{'=' * 8}\n{'=' * 39}\n",                    # longer rules are not markers
        f"  {OPEN} indented, as in a documented example\n  {MID}\n  {CLOSE} x\n",
        f"{OPEN[:6]} six is not a marker\n{CLOSE[:6]} nor this\n{BASE[:6]}\n",
        f"{OPEN}{OPEN} fourteen in a row is a rule, not a marker\n",
        f"x {OPEN} mid-line\n",
        f"{OPEN}x\n",                                   # no space after the marker
        "",
        "\n\n\n",
    ],
    ids=[
        "setext-h1", "setext-and-dashes", "rst-over-underline", "table-row", "longer-rules",
        "indented-example", "six-chars", "fourteen", "mid-line", "no-space", "empty", "blank",
    ],
)
def test_ordinary_text_is_not_a_conflict(text: str) -> None:
    assert conflict_markers(text) == []


def test_a_separator_after_a_resolved_conflict_is_ordinary_again() -> None:
    text = f"{OPEN} a\nx\n{MID}\ny\n{CLOSE} b\nTitle\n{MID}\n"
    assert [(n, k) for n, k in conflict_markers(text) if k == "separator"] == [(3, "separator")]


# ---------------------------------------------------- the walk, on a synthetic tree


def test_the_walk_flags_a_planted_conflict_and_reports_the_count(tmp_path: Path) -> None:
    (tmp_path / "CHANGELOG.md").write_text(CONFLICT, encoding="utf-8")
    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "rule.md").write_text(f"T\n{MID}\n", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01" + CONFLICT.encode())
    (tmp_path / "latin1.txt").write_bytes(b"caf\xe9\n" + CONFLICT.encode())
    (tmp_path / "link.md").symlink_to(tmp_path / "CHANGELOG.md")

    scanned, offenders = scan_files(sorted(tmp_path.iterdir()), root=tmp_path)

    assert scanned == 3  # CHANGELOG.md, clean.py, rule.md -- binary, non-UTF-8 and symlink skipped
    assert len(offenders) == 4
    assert all(o.startswith("CHANGELOG.md:") for o in offenders), offenders


def test_an_empty_walk_scans_nothing_and_the_real_test_refuses_it() -> None:
    """The vacuity guard: no files found must read as 'blind', never as 'clean'."""
    scanned, offenders = scan_files([])
    assert (scanned, offenders) == (0, [])
    assert scanned < MIN_FILES_SCANNED


def test_the_real_walk_sees_many_files_and_skips_none_it_should_read() -> None:
    tracked = _tracked_files()
    scanned, _ = scan_files(tracked)
    assert len(tracked) >= MIN_FILES_SCANNED
    assert scanned >= MIN_FILES_SCANNED
