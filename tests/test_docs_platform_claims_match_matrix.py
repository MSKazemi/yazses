"""No user-facing page claims more platform support than the validation matrix proves.

ADR-030 Pillar 1, items 1 and 2: macOS and Windows stay labelled **preview** until a named
human has recorded dictation on a current build, graded *Verified (HW)* in
`docs/validation-matrix.md`; the label comes off per OS. Linux X11 needs the same
versioned record before any page calls it verified (#642). And no page says "full
Wayland" until dictation is verified on GNOME and KDE hardware (#643).

The set of verified platforms is **read from the matrix**, never written here. A
hand-written list would be the defect this file exists to prevent: it would stay true
on the day it was typed and go on asserting it after the matrix moved. So the guards
arm and disarm themselves:

* an OS counts as verified for dictation when one of its matrix rows grades both
  *Capture + transcription* and *Text injection* **Verified (HW)** and names the
  version tested. Whether that version is still "current" is the grader's call under
  the evidence standard (`docs/contribute/validation.md`); a later release does not
  inherit a cell, and the maintainer re-grades it.
* Wayland counts as verified when a GNOME Wayland row **and** a KDE Wayland row both do.
* X11 counts as verified when an X11 row does.

What is checked, for every platform the matrix does not yet verify:

1. prose does not call it something stronger than preview ("fully supported",
   "verified", "production-ready", ...) unless the same sentence negates it
   ("not yet verified");
2. any table cell that states YazSes's support for it says "preview" (or is a "No");
3. the headline pages — README, home, platform support, quick start, FAQ, comparison,
   and each OS's install guide — carry the word "preview" next to the OS name;
4. nothing says "full Wayland", in prose or as a "Full" table cell.

What is deliberately **not** scanned, and why:

* `CHANGELOG.md` (outside the scanned tree) and `docs/releases/` — release notes are a
  dated record of what each release said. Rewriting a past note to today's evidence
  would falsify history, and a historical sentence is not a present claim.
* `docs/validation-matrix.md` — the evidence itself, read here as the source of truth.
* `docs/contribute/` — the tester-facing pages that define the grades; "Verified (HW)"
  there is an instruction, not a claim about YazSes.
* the generated references (`features.md`, `configuration.md`, `command-index.md`) —
  `scripts/gen-docs.py` writes them, they describe commands rather than platforms, and
  a hit there could not be fixed by hand anyway.
* translated locale trees (an `index.md` carrying a `yazses-l10n:` marker) — the
  wording belongs to their translators and these English patterns cannot read it.
* any `adr/` directory — a decision record describes the context on the day of the
  decision.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MATRIX = DOCS / "validation-matrix.md"

#: The two desktop operating systems the preview rule governs. Linux is the platform
#: the project leads with; its sessions are governed by rules 1 (X11) and 4 (Wayland).
PREVIEW_OSES = ("macOS", "Windows")

#: The matrix columns that together mean "a person dictated and the text arrived".
DICTATION_COLUMNS = ("Capture + transcription", "Text injection")
VERIFIED = "Verified (HW)"
VERSION = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b")

# --- the pages ------------------------------------------------------------------------

EXCLUDED_TREES = frozenset({"releases", "contribute"})
EXCLUDED_FILES = frozenset({
    "validation-matrix.md",
    "features.md",
    "configuration.md",
    "command-index.md",
})

#: Pages that must say "preview" next to each unverified OS they cover. These are the
#: pages a newcomer reads to decide whether YazSes runs on their machine.
HEADLINE_PAGES = {
    "README.md": PREVIEW_OSES,
    "docs/index.md": PREVIEW_OSES,
    "docs/platform-support.md": PREVIEW_OSES,
    "docs/get-started.md": PREVIEW_OSES,
    "docs/faq.md": PREVIEW_OSES,
    "docs/comparison.md": PREVIEW_OSES,
    "docs/macos-install.md": ("macOS",),
    "docs/windows-install.md": ("Windows",),
}

#: How close "preview" must sit to the OS name on a headline page, in characters.
PREVIEW_WINDOW = 300

# --- the detectors --------------------------------------------------------------------

#: Up to 40 characters of the same sentence: no sentence end, no table-cell pipe, no
#: code span, no blank line.
_GAP = r"(?:(?!\n\s*\n)[^.!?|`]){0,%d}?"

#: Wording stronger than "preview". `verified` must stand alone or follow "hardware":
#: "checksum-verified installer" is a statement about a download, not the platform.
_STRONG = (
    r"(?i:fully[ -]supported|full(?:y)?[ -]support|full[ -]featured|(?<![\w-])verified"
    r"|hardware[ -]verified|production[ -]ready|first[ -]class|officially[ -]supported"
    r"|battle[ -]tested|rock[ -]solid|stable[ -]release|out[ -]of[ -](?:beta|preview)"
    r"|generally[ -]available)"
)
_VERIFIED_WORD = r"(?i:(?<![\w-])verified|hardware[ -]verified)"


def _near(subject: str, word: str, gap: int = 40) -> re.Pattern[str]:
    g = _GAP % gap
    return re.compile(rf"\b{subject}\b{g}\b{word}\b|\b{word}{g}\b{subject}\b")


#: Case-sensitive on the OS name on purpose: "windows" in lower case is a GUI window.
OS_STRONG = {os_name: _near(os_name, _STRONG) for os_name in PREVIEW_OSES}
OS_STRONG["macOS"] = _near(r"(?:macOS|Mac)", _STRONG)
X11_VERIFIED = _near("X11", _VERIFIED_WORD)
FULL_WAYLAND = re.compile(
    r"(?i:\bfull(?:y)?[ -]+(?:supported[ -]+(?:on|for)[ -]+|support[ -]+(?:on|for)[ -]+)?)"
    r"Wayland\b"
    r"|\bWayland\b" + (_GAP % 25) + r"(?i:\bfull(?:y[ -]supported|[ -]support)\b)"
)

#: A sentence that negates or defers the claim is not making it: "not yet verified",
#: "no page claims full Wayland until ...".
NEGATION = re.compile(
    r"\b(?:not|never|no|nobody|none|until|unless|once|before|without|yet\s+to)\b", re.I
)


def _sentence_up_to(text: str, m: re.Match[str]) -> str:
    """The sentence that holds a match, from its start to the end of the match."""
    head = text[: m.start()]
    cut = max(head.rfind(c) for c in (". ", ".\n", "! ", "? ", "\n\n", "|"))
    return text[cut + 1 : m.end()]


def claims(pattern: re.Pattern[str], text: str) -> list[str]:
    """Every un-negated match of `pattern` in `text`, as the offending sentence."""
    out = []
    for m in pattern.finditer(text):
        sentence = _sentence_up_to(text, m)
        if NEGATION.search(sentence):
            continue
        out.append(" ".join(sentence.split())[-160:])
    return out


# --- markdown tables ------------------------------------------------------------------


def _cells(line: str) -> list[str]:
    inner = line.strip().strip("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def _is_rule(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def tables(text: str) -> list[tuple[str, list[list[str]]]]:
    """Every markdown table as (heading above it, rows including the header row)."""
    out: list[tuple[str, list[list[str]]]] = []
    heading, current = "", None
    for line in text.splitlines():
        stripped = line.strip()
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        if stripped.startswith("|"):
            cells = _cells(stripped)
            if current is None:
                current = (heading, [])
                out.append(current)
            if not _is_rule(cells):
                current[1].append(cells)
        else:
            current = None
    return out


def _plain(cell: str) -> str:
    return cell.replace("*", "").replace("_", " ").strip()


_YAZSES = re.compile(r"\bYazSes\b")


def yazses_cells(rows: list[list[str]]) -> list[tuple[str, str]]:
    """(label, cell) for every cell of a table that states something about YazSes.

    Two orientations occur: YazSes as a column (README, the compare pages) and YazSes as
    a row (comparison.md, llms.txt). The label is the other axis's header.
    """
    if len(rows) < 2:
        return []
    header, body = rows[0], rows[1:]
    out = []
    for i, h in enumerate(header):
        if i and _YAZSES.search(h):
            out.extend((r[0], r[i]) for r in body if len(r) > i)
    for r in body:
        if r and _YAZSES.search(r[0]):
            out.extend((header[i], r[i]) for i in range(1, min(len(header), len(r))))
    return out


_PLATFORM_LABEL = re.compile(r"\b(?:Platforms?|Operating systems?|OS)\b")
_NEGATIVE_CELL = re.compile(r"^(?:❌|no\b|not\b|—|-|n/a\b)", re.I)


def unlabelled_os_cells(text: str, unverified: frozenset[str]) -> list[str]:
    """YazSes table cells that affirm an unverified OS without saying "preview"."""
    bad = []
    for heading, rows in tables(text):
        for label, cell in yazses_cells(rows):
            plain = _plain(cell)
            if not plain or _NEGATIVE_CELL.match(plain) or "preview" in plain.lower():
                continue
            label_names = {o for o in unverified if re.search(rf"\b{o}\b", label)}
            cell_names = {o for o in unverified if re.search(rf"\b{o}\b", cell)}
            if label_names or (_PLATFORM_LABEL.search(label) and cell_names):
                bad.append(f"[{heading}] {_plain(label)}: {plain[:80]}")
    return bad


def full_wayland_cells(text: str) -> list[str]:
    bad = []
    for heading, rows in tables(text):
        for label, cell in yazses_cells(rows):
            if "Wayland" in label and re.match(r"full\b", _plain(cell), re.I):
                bad.append(f"[{heading}] {_plain(label)}: {_plain(cell)[:80]}")
    return bad


# --- the matrix -----------------------------------------------------------------------


def _grade(cell: str) -> str:
    return cell.lstrip("* ")


def dictation_verified(matrix_text: str) -> dict[str, list[str]]:
    """OS section -> the setups a named human verified dictation on, with a version."""
    sections: dict[str, list[list[str]]] = {}
    for heading, rows in tables(matrix_text):
        if heading in ("macOS", "Windows", "Linux"):
            sections[heading] = rows
    out: dict[str, list[str]] = {}
    for os_name, rows in sections.items():
        header = rows[0]
        missing = [c for c in DICTATION_COLUMNS if c not in header]
        assert not missing, f"matrix '## {os_name}' has no column {missing} -- this guard is blind"
        cols = [header.index(c) for c in DICTATION_COLUMNS]
        out[os_name] = [
            _plain(row[0])
            for row in rows[1:]
            if len(row) > max(cols)
            and all(
                _grade(row[c]).startswith(VERIFIED) and VERSION.search(row[c]) for c in cols
            )
        ]
    return out


def platform_state(matrix_text: str) -> tuple[frozenset[str], bool, bool]:
    """(unverified preview OSes, X11 verified, Wayland verified on GNOME and KDE)."""
    verified = dictation_verified(matrix_text)
    unverified = frozenset(o for o in PREVIEW_OSES if not verified.get(o))
    linux = verified.get("Linux", [])
    x11 = any("X11" in s for s in linux)
    wayland = all(
        any(desktop in s and "Wayland" in s for s in linux) for desktop in ("GNOME", "KDE")
    )
    return unverified, x11, wayland


UNVERIFIED, X11_IS_VERIFIED, WAYLAND_IS_VERIFIED = platform_state(
    MATRIX.read_text(encoding="utf-8")
)


def _locale_dirs() -> frozenset[str]:
    return frozenset(
        d.name
        for d in DOCS.iterdir()
        if d.is_dir()
        and (d / "index.md").is_file()
        and "yazses-l10n:" in (d / "index.md").read_text(encoding="utf-8")
    )


def scanned_pages() -> list[Path]:
    skip_trees = EXCLUDED_TREES | _locale_dirs()
    pages = [ROOT / "README.md", ROOT / "llms.txt", DOCS / "llms.txt"]
    for path in sorted(DOCS.rglob("*.md")):
        rel = path.relative_to(DOCS)
        if rel.parts[0] in skip_trees or "adr" in rel.parts[:-1]:
            continue
        if rel.as_posix() in EXCLUDED_FILES:
            continue
        pages.append(path)
    return pages


PAGES = scanned_pages()


def _id(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


# --- guard the guard ------------------------------------------------------------------


def test_the_matrix_parser_sees_all_three_platforms():
    verified = dictation_verified(MATRIX.read_text(encoding="utf-8"))
    assert set(verified) == {"macOS", "Windows", "Linux"}, verified


def test_the_page_set_is_the_one_a_reader_sees():
    names = {_id(p) for p in PAGES}
    for must in (*HEADLINE_PAGES, "docs/compare/yazses-vs-handy.md", "docs/llms.txt"):
        assert must in names, f"{must} is not scanned"
    assert len(PAGES) >= 60, f"only {len(PAGES)} pages scanned -- a filter is too wide"
    assert not any("/releases/" in n for n in names), "release notes leaked into the scan"


def test_the_table_check_has_tables_to_read():
    """A table extractor that finds no YazSes-vs-OS cells would pass forever."""
    found = 0
    for page in PAGES:
        for _heading, rows in tables(page.read_text(encoding="utf-8")):
            found += sum(
                1
                for label, cell in yazses_cells(rows)
                if re.search(r"\b(?:macOS|Windows)\b", label + " " + cell)
            )
    assert found >= 8, f"only {found} YazSes table cells about macOS/Windows found"


_MATRIX_HEADER = (
    "| Setup | Install | First launch | Permissions | Capture + transcription "
    "| Text injection | Start / restart / stop | Update path | Last human validation "
    "| Gap / next tester |\n|---|---|---|---|---|---|---|---|---|---|\n"
)


def _fake_matrix(mac_capture: str, mac_inject: str, linux_rows: str = "") -> str:
    blank = "| x | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | none | x |\n"
    mac = f"| **Mac** | a | b | c | {mac_capture} | {mac_inject} | d | e | f | g |\n"
    return (
        "## macOS\n\n" + _MATRIX_HEADER + mac + "\n## Windows\n\n" + _MATRIX_HEADER + blank
        + "\n## Linux\n\n" + _MATRIX_HEADER + (linux_rows or blank)
    )


@pytest.mark.parametrize(
    ("capture", "inject", "mac_verified"),
    [
        ("**Verified (HW)** E1. 2.44.0", "**Verified (HW)** E1. 2.44.0", True),
        ("**Verified (HW)** E1. 2.44.0", "**Blocked** E3. #562", False),
        ("**Verified (HW)** E1, no version", "**Verified (HW)** E1, no version", False),
        ("**Reported** E1. 2.44.0", "**Reported** E1. 2.44.0", False),
    ],
)
def test_the_verified_set_comes_from_the_matrix(capture, inject, mac_verified):
    unverified, _x11, _wayland = platform_state(_fake_matrix(capture, inject))
    assert ("macOS" not in unverified) is mac_verified
    assert "Windows" in unverified


def test_wayland_needs_both_gnome_and_kde():
    v = "**Verified (HW)** E9. 2.44.0"
    row = "| **{}** | a | b | c | " + v + " | " + v + " | d | e | f | g |\n"
    gnome_only = _fake_matrix("x", "x", row.format("Ubuntu, GNOME Wayland"))
    both = _fake_matrix(
        "x", "x", row.format("Ubuntu, GNOME Wayland") + row.format("Kubuntu, KDE Wayland")
    )
    x11 = _fake_matrix("x", "x", row.format("Ubuntu, GNOME X11"))
    assert platform_state(gnome_only)[2] is False
    assert platform_state(both)[2] is True
    assert platform_state(x11)[1] is True and platform_state(x11)[2] is False


@pytest.mark.parametrize(
    ("pattern", "text"),
    [
        (FULL_WAYLAND, "YazSes is the better choice if you want **full Wayland support**."),
        (FULL_WAYLAND, "Wayland is fully supported on every desktop."),
        (FULL_WAYLAND, "Full support for Wayland, out of the box."),
        (OS_STRONG["macOS"], "macOS is fully supported."),
        (OS_STRONG["Windows"], "Verified on Windows 11 by our testers."),
        (OS_STRONG["Windows"], "Windows support is production-ready."),
        (X11_VERIFIED, "Dictation is verified on X11."),
    ],
)
def test_the_detectors_catch_an_overclaim(pattern, text):
    assert claims(pattern, text), f"missed: {text!r}"


@pytest.mark.parametrize(
    ("pattern", "text"),
    [
        (OS_STRONG["macOS"], "macOS has not yet been verified on hardware by a person."),
        (OS_STRONG["Windows"], "Windows is in preview: supported, not yet verified."),
        (OS_STRONG["Windows"], "The overlay windows are verified at startup."),
        (OS_STRONG["Windows"], "A checksum-verified installer for Windows."),
        (FULL_WAYLAND, "No page claims full Wayland until GNOME and KDE are verified."),
        (X11_VERIFIED, "A versioned X11 record is still to come; X11 is not verified yet."),
    ],
)
def test_the_detectors_leave_honest_wording_alone(pattern, text):
    assert not claims(pattern, text), f"false positive: {text!r}"


def test_a_yes_cell_without_preview_is_caught():
    text = "| | Handy | YazSes |\n|---|---|---|\n| macOS / Windows | Yes | Yes |\n"
    assert unlabelled_os_cells(text, frozenset(PREVIEW_OSES))
    ok = text.replace("| Yes |\n", "| Yes (preview) |\n")
    assert not unlabelled_os_cells(ok, frozenset(PREVIEW_OSES))
    platforms = "| Tool | Platforms |\n|---|---|\n| **YazSes** | Linux, macOS, Windows |\n"
    assert unlabelled_os_cells(platforms, frozenset(PREVIEW_OSES))
    assert not unlabelled_os_cells(platforms, frozenset())


def test_a_full_wayland_cell_is_caught():
    text = "| | Handy | YazSes |\n|---|---|---|\n| Linux Wayland | Limited | **Full** — probe |\n"
    assert full_wayland_cells(text)


# --- the rules ------------------------------------------------------------------------


@pytest.mark.parametrize("page", PAGES, ids=_id)
def test_no_page_calls_an_unverified_os_more_than_preview(page):
    text = page.read_text(encoding="utf-8")
    found = [c for os_name in sorted(UNVERIFIED) for c in claims(OS_STRONG[os_name], text)]
    assert not found, (
        f"{_id(page)} calls an OS the validation matrix has not verified more than "
        f"'preview':\n  " + "\n  ".join(found)
        + "\nSay 'supported, preview — not yet verified on hardware by a person' and link "
        "docs/validation-matrix.md (ADR-030 Pillar 1.1)."
    )


@pytest.mark.parametrize("page", PAGES, ids=_id)
def test_yazses_table_cells_label_unverified_oses_preview(page):
    found = unlabelled_os_cells(page.read_text(encoding="utf-8"), UNVERIFIED)
    assert not found, (
        f"{_id(page)} has a table cell stating YazSes runs on an OS the validation "
        f"matrix has not verified, without 'preview':\n  " + "\n  ".join(found)
    )


@pytest.mark.parametrize(
    ("rel", "os_name"),
    [(rel, o) for rel, oses in HEADLINE_PAGES.items() for o in oses],
)
def test_headline_pages_label_each_unverified_os_preview(rel, os_name):
    if os_name not in UNVERIFIED:
        pytest.skip(f"{os_name} has a Verified (HW) dictation row; the label may come off")
    text = (ROOT / rel).read_text(encoding="utf-8")
    labelled = any(
        re.search(r"preview", text[max(0, m.start() - PREVIEW_WINDOW) : m.end() + PREVIEW_WINDOW], re.I)
        for m in re.finditer(rf"\b{os_name}\b", text)
    )
    assert labelled, (
        f"{rel} names {os_name} but never calls it 'preview' near the name, while the "
        f"validation matrix has no Verified (HW) dictation for it (ADR-030 Pillar 1.1)."
    )


@pytest.mark.parametrize("page", PAGES, ids=_id)
def test_no_page_says_full_wayland(page):
    if WAYLAND_IS_VERIFIED:
        pytest.skip("GNOME and KDE Wayland both have Verified (HW) dictation rows")
    text = page.read_text(encoding="utf-8")
    found = claims(FULL_WAYLAND, text) + full_wayland_cells(text)
    assert not found, (
        f"{_id(page)} claims full Wayland before GNOME and KDE dictation is verified on "
        f"hardware (#643):\n  " + "\n  ".join(found)
    )


@pytest.mark.parametrize("page", PAGES, ids=_id)
def test_no_page_calls_x11_verified_without_a_versioned_record(page):
    if X11_IS_VERIFIED:
        pytest.skip("an X11 row has a Verified (HW) dictation record")
    found = claims(X11_VERIFIED, page.read_text(encoding="utf-8"))
    assert not found, (
        f"{_id(page)} calls X11 verified, but the validation matrix has no versioned "
        f"Verified (HW) X11 record yet (#642):\n  " + "\n  ".join(found)
    )
