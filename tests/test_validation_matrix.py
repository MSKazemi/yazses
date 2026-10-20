"""The validation matrix must not claim what it cannot cite.

`docs/validation-matrix.md` exists to tell a newcomer what a person has actually run on a
real machine. Its only value is that a cell is never more confident than its evidence, so
this guard holds the three properties that keep it so, and nothing else:

* every cell in the platform tables uses one word from the published vocabulary;
* every cell that is not UNVERIFIED names an evidence row (`E<n>`) that exists in the log,
  and a Blocked cell also names the issue that blocks it;
* every row in the evidence log carries a link a reader can follow.

It deliberately does not check that the evidence is *true* (a person read the thread and a
person must re-read it) nor that a status is the *right* one. Those are judgements. What a
script can refuse is a confident cell with nothing behind it, which is the failure that
makes a support matrix a rumour.

The privacy half is separate: the two contributor-facing pages ask volunteers to paste
`doctor` output, and must not themselves contain a home path or an address.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MATRIX = DOCS / "validation-matrix.md"
STANDARD = DOCS / "contribute" / "validation.md"
MACOS = DOCS / "contribute" / "macos-validation.md"

#: The vocabulary. Keep in step with the table in docs/contribute/validation.md; a test
#: below fails if either page stops naming one of these.
WORDS = ("Verified (HW)", "Failed (HW)", "CI only", "Reported", "Blocked", "UNVERIFIED")

#: Columns of the platform tables that hold a status: Install .. Update path.
FIRST_STATUS_COL, LAST_STATUS_COL = 1, 7

EVIDENCE_ID = re.compile(r"\bE\d+\b")
ISSUE_REF = re.compile(r"/issues/\d+|#\d+")
URL = re.compile(r"https?://\S+")


def _cells(line: str) -> list[str]:
    """Split a markdown table row on pipes that are not inside a link or code span."""
    inner = line.strip().strip("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def _tables(text: str) -> dict[str, list[list[str]]]:
    """Map each `##` heading to the table rows (header and rule excluded) under it."""
    out: dict[str, list[list[str]]] = {}
    heading = ""
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            out.setdefault(heading, [])
        elif heading and line.startswith("|"):
            cells = _cells(line)
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                continue
            out[heading].append(cells)
    for heading in out:
        out[heading] = out[heading][1:] if out[heading] else []
    return out


def _platform_rows() -> list[tuple[str, list[str]]]:
    tables = _tables(MATRIX.read_text(encoding="utf-8"))
    rows = []
    for name in ("macOS", "Windows", "Linux"):
        assert tables.get(name), f"no table found under '## {name}' -- the parser is checking nothing"
        rows.extend((name, r) for r in tables[name])
    return rows


def _evidence_log() -> dict[str, str]:
    tables = _tables(MATRIX.read_text(encoding="utf-8"))
    log = {}
    for row in tables["Evidence log"]:
        log[row[0]] = " | ".join(row[1:])
    return log


def _status_cells() -> list[tuple[str, str, str]]:
    cells = []
    for os_name, row in _platform_rows():
        assert len(row) == 10, f"{os_name} row '{row[0][:40]}' has {len(row)} columns, expected 10"
        for col in range(FIRST_STATUS_COL, LAST_STATUS_COL + 1):
            cells.append((row[0], str(col), row[col]))
    return cells


def _word_of(cell: str) -> str | None:
    bare = cell.removeprefix("**")
    for word in WORDS:
        if bare.startswith(word):
            return word
    return None


def test_there_are_cells_to_check():
    """Guard the guard: a parser that finds nothing would pass forever."""
    assert len(_platform_rows()) >= 10
    assert len(_status_cells()) >= 70
    assert len(_evidence_log()) >= 10


@pytest.mark.parametrize(
    ("row", "col", "cell"),
    _status_cells(),
    ids=lambda v: re.sub(r"[^A-Za-z0-9]+", "-", v)[:24],
)
def test_every_cell_uses_the_vocabulary_and_cites_its_evidence(row, col, cell):
    word = _word_of(cell)
    assert word, f"{row!r} column {col}: cell does not start with one of {WORDS}: {cell[:80]!r}"
    if word == "UNVERIFIED":
        return
    ids = EVIDENCE_ID.findall(cell)
    assert ids, f"{row!r} column {col}: '{word}' cell cites no evidence row (E<n>)"
    log = _evidence_log()
    missing = [i for i in ids if i not in log]
    assert not missing, f"{row!r} column {col}: cites {missing}, not in the evidence log"
    if word == "Blocked":
        assert ISSUE_REF.search(cell), f"{row!r} column {col}: Blocked must name the blocking issue"


def test_every_evidence_row_has_a_link():
    for ident, rest in _evidence_log().items():
        assert URL.search(rest), f"{ident}: evidence row has no link a reader can follow"


def test_every_evidence_row_is_used():
    text = MATRIX.read_text(encoding="utf-8")
    body = text.split("## Evidence log")[0]
    for ident in _evidence_log():
        assert re.search(rf"\b{ident}\b", body), f"{ident} is in the log but no cell or note cites it"


def test_both_pages_name_the_same_vocabulary():
    for page in (MATRIX, STANDARD):
        text = page.read_text(encoding="utf-8")
        for word in WORDS:
            assert word in text, f"{page.name} no longer names '{word}'"


@pytest.mark.parametrize("page", [MATRIX, STANDARD, MACOS], ids=lambda p: p.name)
def test_the_pages_are_in_the_nav(page):
    nav = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    rel = page.relative_to(DOCS).as_posix()
    assert f": {rel}\n" in nav, f"{rel} is not in mkdocs.yml nav"


@pytest.mark.parametrize("page", [MATRIX, STANDARD, MACOS], ids=lambda p: p.name)
def test_the_pages_carry_no_personal_paths_or_addresses(page):
    text = page.read_text(encoding="utf-8")
    assert not re.search(r"/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|C:\\Users", text)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), "an email address is in the page"
