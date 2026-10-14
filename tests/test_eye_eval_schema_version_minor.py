"""`schema_version` is "MAJOR.MINOR" -- and the MINOR half was never looked at.

`validate_result` split on "." and checked only that the part before it was digits, so
`"1.x"`, `"1."` and `"1.-1"` read as major 1 and were accepted as a well-formed version. The
sibling `fixture_schema_version` in `eyeeval/tasks.py` already checks both halves ("1.x is
refused on purpose: the minor part is checked, not merely tolerated"); the result schema
should not be the looser of the two.

The documented policy stays as it was and is pinned here: a *forward-compatible* minor is
accepted (`"1.999"` is a later 1.x that only added fields), a malformed one is refused, and
a different major is refused with the major-version message. `str.isdigit()` is not the
right test either -- it is true for Arabic-Indic and superscript digits, and `int()` happily
converts some of them -- so the parser is ASCII-only and has a length cap, since
`int("9" * 5000)` raises past Python's integer-string limit.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from yazses.eyeeval import validate_result
from yazses.eyeeval.schema import SCHEMA_VERSION, SUPPORTED_MAJOR, parse_schema_version
from yazses.eyeeval.tasks import validate_task

FIXTURES = Path(__file__).parent / "fixtures" / "eye_eval"

def repr_short(value: str) -> str:
    """Keep a 5000-digit case from becoming a 5000-character test id."""
    return repr(value) if len(value) < 24 else f"{value[:6]!r}...({len(value)} chars)"


MALFORMED = [
    "1.x", "1.", ".1", ".", "1.-1", "1.+1", "1. 1", " 1.0", "1.0 ", "1.0\n", "1.0.0", "1..0",
    "1.0-beta", "1.0rc1", "1,0", "v1.0", "1", "", "one.two", "01.0", "1.01", "1.00",
    "1.١",          # Arabic-Indic digit one: isdigit() is True, not a schema version
    "١.0",          # ... in the major position too
    "1.²",          # superscript two: isdigit() True, int() raises
    "1." + "9" * 5000,   # past int()'s string-length limit
    "1.9999999999",      # a minor nobody would ever write
]


@pytest.fixture
def doc() -> dict:
    return json.loads((FIXTURES / "gaze_community_qa.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("bad", MALFORMED, ids=repr_short)
def test_a_malformed_version_is_refused_with_only_the_version_complaint(doc, bad):
    doc["schema_version"] = bad
    problems = validate_result(doc)
    assert len(problems) == 1 and problems[0].startswith("schema_version:"), problems
    assert parse_schema_version(bad) is None


@pytest.mark.parametrize("bad", [None, 1, 1.0, True, [], {}, b"1.0"])
def test_a_non_string_version_is_refused(doc, bad):
    doc["schema_version"] = bad
    problems = validate_result(doc)
    assert len(problems) == 1 and problems[0].startswith("schema_version:"), problems


@pytest.mark.parametrize("good", ["1.0", "1.1", "1.7", "1.10", "1.999"])
def test_a_forward_compatible_minor_is_accepted(doc, good):
    """The documented policy: same MAJOR is readable, whatever a later minor added."""
    doc["schema_version"] = good
    assert validate_result(doc) == []


def test_a_missing_version_is_refused(doc):
    doc.pop("schema_version")
    problems = validate_result(doc)
    assert len(problems) == 1 and problems[0].startswith("schema_version:"), problems


@pytest.mark.parametrize("other", ["0.9", "2.0", "2.5", "10.0"])
def test_a_different_major_still_gets_the_major_version_message(doc, other):
    doc["schema_version"] = other
    problems = validate_result(doc)
    assert len(problems) == 1 and "major version" in problems[0], problems


def test_the_parser_returns_both_halves_as_integers():
    assert parse_schema_version("1.0") == (1, 0)
    assert parse_schema_version("1.999") == (1, 999)
    assert parse_schema_version("0.0") == (0, 0)
    assert parse_schema_version(SCHEMA_VERSION) == (SUPPORTED_MAJOR, 0)


@pytest.mark.parametrize("bad", MALFORMED, ids=repr_short)
def test_a_fixture_version_obeys_the_same_grammar(bad):
    """tasks.py kept its own looser copy (`isdigit`); one grammar, one parser."""
    task = json.loads(
        (Path(__file__).parent / "fixtures" / "eye_eval_tasks" / "gaze_routing_4_pane.json")
        .read_text(encoding="utf-8")
    )
    task["fixture_schema_version"] = bad
    problems = validate_task(task)
    assert len(problems) == 1 and problems[0].startswith("fixture_schema_version:"), problems
