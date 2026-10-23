"""A SHOWCASE entry that copies another one word for word is refused.

A setup report earns its author a place on the contributors wall as a tester, so it has to
be their own. PR #548 (2026-09-28) added an entry whose every line, including the "How you
use YazSes" paragraph, was copied from an existing one. The linter checked only the shape
of each entry on its own, so a verbatim copy passed.

The signal is deliberately narrow (AGENTS.md rule 9): only an identical "How you use
YazSes" text, after case and whitespace are normalised, and only when it is long enough to
be personal. Two people who both write "dictating notes." are not copying each other.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cc():
    spec = importlib.util.spec_from_file_location(
        "check_compatibility", ROOT / "scripts" / "check-compatibility.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


USE = (
    "Mostly for typing while coding and working on GitHub. It's nice being able to just hold "
    "the key, say what I want, and have it appear wherever I'm working."
)


def _entry(use: str, os_line: str = "Windows 11") -> str:
    return (
        f"- **OS / desktop:** {os_line}\n"
        "- **Mic:** laptop built-in microphone\n"
        "- **Apps you dictate into:** VS Code, PowerShell\n"
        f"- **How you use YazSes:** {use}\n"
    )


def test_a_verbatim_copy_of_an_earlier_entry_is_refused(cc):
    found = [("@first", _entry(USE)), ("@second", _entry(USE))]
    problems = cc.copied_entries(found)
    assert len(problems) == 1
    assert "@second" in problems[0] and "@first" in problems[0]


def test_case_and_line_wrapping_do_not_hide_a_copy(cc):
    rewrapped = USE.upper().replace(" and ", "\n  and ")
    found = [("@first", _entry(USE)), ("@second", _entry(rewrapped))]
    assert len(cc.copied_entries(found)) == 1


def test_an_entry_in_its_own_words_passes(cc):
    found = [("@first", _entry(USE)), ("@second", _entry("I dictate commit messages in VS Code."))]
    assert cc.copied_entries(found) == []


def test_a_short_common_phrase_is_not_a_copy(cc):
    found = [("@first", _entry("dictating notes.")), ("@second", _entry("Dictating notes."))]
    assert cc.copied_entries(found) == []


def test_the_committed_showcase_has_no_copies(cc):
    found = cc.entries((ROOT / "SHOWCASE.md").read_text(encoding="utf-8"))
    assert cc.copied_entries(found) == []


def test_main_fails_on_a_copy(cc, tmp_path):
    f = tmp_path / "SHOWCASE.md"
    f.write_text(f"### @first\n{_entry(USE)}\n### @second\n{_entry(USE)}\n", encoding="utf-8")
    assert cc.main(["--file", str(f)]) == 1


def test_an_indented_heading_is_still_an_entry(cc):
    """#548's copy sat under `  ### @Athith`. Markdown renders up to three spaces of indent
    as a heading, so the linter must read it as one -- or the copy hides inside the entry
    above it and every check passes."""
    md = f"### @first\n{_entry(USE)}\n  ### @second\n{_entry(USE)}\n"
    found = cc.entries(md)
    assert [h for h, _ in found] == ["@first", "@second"]
    assert len(cc.copied_entries(found)) == 1


def test_a_trailing_comment_or_blank_line_does_not_hide_a_copy(cc):
    """In #548 the copied entry was the last one, followed by the file's HTML comment; the
    answer ran on into it and no longer matched."""
    md = (
        f"### @first\n{_entry(USE)}\n  ### @second\n{_entry(USE)}    \n"
        "<!-- Add your entry above this line's section by appending a new ### block. -->\n"
    )
    assert len(cc.copied_entries(cc.entries(md))) == 1
