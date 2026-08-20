"""A page that promises the log holds no dictated text must name the setting that changes it.

`[general] log_level = "DEBUG"` is a supported setting — it is what
`docs/cli-reference.md` tells you to turn on to see what the daemon actually decided —
and it puts each transcript into `daemon.log` on disk. `core/daemon.py` states the split
where it writes them:

    # INFO: metadata only (length); DEBUG: the actual text.
    log.info("Injecting %d chars, %d words.", len(text), len(text.split()))
    log.debug("Injecting text: %r", text)

Measured through the real `Daemon._configure_logging` into a temp directory, emitting from
the real call site: at `"INFO"` the sentence is absent from `daemon.log`; at `"DEBUG"` it
is there in full. Nothing is uploaded either way (ADR-011) — the file is local — but it is
the difference between a log you can hand to someone and one you cannot.

`system/report.py` was taught this in `18e0d7a` and drops every DEBUG line from the bundle.
The documentation was not. Five pages carried the promise with no condition attached, and
the worst of them was `docs/privacy-statement.md`, the page a privacy-conscious reader
trusts most, which stated flatly that the transcript *"is not written to any log file"* and
that the log records *"metadata only … never your dictated text"*. `docs/cli-reference.md`
was the single page that already told the truth — *"The actual transcript text is logged
only when `general.log_level = "DEBUG"`"* — which is also what makes it the shape to copy.

## Page-level, like `test_docs_qualify_the_unwired_slm_router.py`

The caveat lands in different places relative to the claim on different pages — an
admonition below a paragraph, a clause inside a table cell, a sentence after a code block —
so a proximity rule fails a page for being correct in the wrong shape.

## Tied to the code, so it cannot outlive its premise

The requirement exists only while some `*.debug(...)` call in `src/` actually passes
dictated text. If that ever stops being true, these pages become honest as written and a
guard still demanding the caveat would be forcing a lie into them.

## Why the report bundle's own header is not in scope

`system/report.py` writes `## Recent log (metadata only — never transcripts)` and that is
true *by construction*: it has just dropped the DEBUG lines and says how many. The scan
anchors on claims about the daemon log as the user reads it (`yazses logs`, `daemon.log`,
"diagnostic log"), which is a different subject from a section of a filtered bundle.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SRC = ROOT / "src" / "yazses"

#: What the claim is *about*. A sentence has to be talking about the daemon's log as the
#: user meets it before "metadata only" is a promise about dictation at all.
LOG_SUBJECT = re.compile(r"yazses logs|daemon\.log|diagnostic log", re.I)

#: The promise itself, in every wording the tree actually used.
NO_TEXT = re.compile(
    r"metadata only"
    r"|never (?:your )?(?:dictated text|transcripts?)"
    r"|no dictated text"
    r"|not written to any log",
    re.I,
)

#: The condition that makes the promise true — the setting, or the level it takes.
CONDITION = re.compile(r"DEBUG|log_level", re.I)

#: Release notes describe what a past version said; editing them is a different untruth.
SKIP_DIRS = ("releases/",)

#: Floors, because a scan whose input quietly empties passes on everything.
_MIN_PAGES = 4
_MIN_DEBUG_SITES = 2


def _pages() -> list[Path]:
    return [
        p for p in sorted(DOCS.rglob("*.md"))
        if not any(d in p.relative_to(ROOT).as_posix() for d in SKIP_DIRS)
    ]


def _claim_lines(body: str) -> list[str]:
    return [
        line for line in body.splitlines()
        if LOG_SUBJECT.search(line) and NO_TEXT.search(line)
    ]


def _claiming_pages() -> dict[Path, list[str]]:
    out = {}
    for page in _pages():
        hits = _claim_lines(page.read_text(encoding="utf-8"))
        if hits:
            out[page] = hits
    return out


def _carries_dictated_text(call: ast.Call) -> bool:
    """A ``…debug(fmt, text)`` / ``…debug(fmt, partial.text)`` call."""
    for arg in call.args[1:]:
        if isinstance(arg, ast.Name) and arg.id == "text":
            return True
        if isinstance(arg, ast.Attribute) and arg.attr == "text":
            return True
    return False


def _debug_text_sites() -> list[tuple[str, int]]:
    """Every place in the shipped tree that writes user text at DEBUG. The premise."""
    sites: list[tuple[str, int]] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "debug"
                and node.args
                and _carries_dictated_text(node)
            ):
                sites.append((path.relative_to(ROOT).as_posix(), node.lineno))
    return sites


def _shipped_strings(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        (n.lineno, n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


# --- the premise ---------------------------------------------------------------

def test_the_log_still_carries_dictated_text_at_debug() -> None:
    sites = _debug_text_sites()
    assert len(sites) >= _MIN_DEBUG_SITES, (
        "nothing in src/ appears to log user text at DEBUG any more. If that is real, the "
        "pages below are honest without a caveat and this guard should be deleted rather "
        f"than satisfied. Found: {sites}"
    )
    assert any(f == "src/yazses/core/daemon.py" for f, _ in sites), sites


# --- the rule ------------------------------------------------------------------

def test_the_scan_sees_the_pages_that_make_the_claim() -> None:
    pages = _claiming_pages()
    assert len(pages) >= _MIN_PAGES, (
        f"only {len(pages)} pages matched; the claim wording probably drifted past the "
        "regex, which would make every assertion below vacuous"
    )


def test_no_page_promises_a_clean_log_without_naming_the_condition() -> None:
    bad = {}
    for page, hits in _claiming_pages().items():
        if not CONDITION.search(page.read_text(encoding="utf-8")):
            bad[page.relative_to(ROOT).as_posix()] = hits
    assert not bad, (
        "these pages promise the log holds no dictated text and never mention that "
        '[general] log_level = "DEBUG" writes each transcript into daemon.log: '
        f"{bad}"
    )


def test_the_shipped_help_for_the_log_names_the_condition() -> None:
    """`yazses logs --help` is read by someone deciding whether the log is shareable."""
    claims = [
        (line, s) for line, s in _shipped_strings(SRC / "cli.py")
        if LOG_SUBJECT.search(s) and NO_TEXT.search(s)
    ]
    assert claims, "no help string describes the log any more — has the command moved?"
    unconditioned = [(line, s) for line, s in claims if not CONDITION.search(s)]
    assert not unconditioned, unconditioned


def test_the_report_bundle_header_is_not_read_as_a_claim_about_the_log() -> None:
    """It is true by construction — `report.py` drops the DEBUG lines before writing it."""
    headers = [
        s for _, s in _shipped_strings(SRC / "system" / "report.py")
        if "metadata only" in s and "never transcripts" in s
    ]
    assert headers, "the bundle's log header changed; re-check that it is still filtered"
    assert not any(LOG_SUBJECT.search(s) for s in headers), (
        "the bundle header now names the daemon log directly, which puts it inside this "
        "guard's subject — either condition it or keep it about the bundle"
    )


# --- the guard's own reach -----------------------------------------------------

def test_the_guard_would_notice_an_unconditioned_claim() -> None:
    page = "# Logs\n\nThe diagnostic log records **metadata only**, never your dictated text.\n"
    assert _claim_lines(page)
    assert not CONDITION.search(page)


def test_the_guard_accepts_the_caveat_wherever_the_page_puts_it() -> None:
    claim = "`yazses logs` shows metadata only.\n"
    for caveat in (
        'Set `[general] log_level = "DEBUG"` to also record transcripts.\n',
        "    Only `DEBUG` adds the text itself.\n",
    ):
        assert CONDITION.search(claim + caveat)


def test_the_claim_detector_ignores_ordinary_prose_about_the_log() -> None:
    for line in (
        "Follow the diagnostic log live with `tail -f`.",
        "`yazses logs --path` prints the log file path and exits.",
        "The corpus stores metadata only in the clear.",  # about the corpus, not the log
    ):
        assert not _claim_lines(line), line
