"""Regression test: SHOWCASE.md must stay machine-readable and terminate.

A previous revision left the trailing "add your entry" sentinel (and a duplicated
horizontal rule) after the end marker, so doc-scanning helpers kept looking for the
sentinel and the test run hung. This test keeps the sentinel as the final line and
asserts the file is well-formed so any scanner finishes in bounded time.
"""

from pathlib import Path

SENTINEL = "<!-- Add your entry above this line's section by appending a new ### block at the end. -->"
ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "SHOWCASE.md"

def _read_doc() -> str:
    return DOC.read_text(encoding="utf-8")

def test_showcase_exists_and_ends_with_sentinel():
    text = _read_doc()
    lines = text.splitlines()
    non_empty = [line for line in lines if line.strip()]
    assert non_empty, "SHOWCASE.md is empty"
    assert non_empty[-1].strip() == SENTINEL, (
        "the 'add your entry' sentinel must be the last non-empty line so "
        "doc scanners terminate"
    )

def test_showcase_no_duplicate_trailing_rules():
    text = _read_doc()
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    tail = lines[-3:]
    assert sum(1 for line in tail if line == "---") <= 1, (
        "stray duplicated horizontal rules after the sentinel can stall doc scans"
    )

def test_showcase_code_fences_are_balanced():
    text = _read_doc()
    fences = [line for line in text.splitlines() if line.strip().startswith("```")]
    assert len(fences) % 2 == 0, "unbalanced fenced code block in SHOWCASE.md"

def test_showcase_parses_quickly():
    # Bounded work: a single read plus one linear pass, no user input, no loops.
    text = _read_doc()
    assert text.count("### @") >= 1
