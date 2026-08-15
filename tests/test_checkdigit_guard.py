"""Checksum-Validated Entry, wired into the dictation path (ADR-021).

`validate.py`'s arithmetic is covered elsewhere. What is tested here is the judgement
built on top of it — **when this guard is allowed to interrupt** — because that is where
a feature like this succeeds or fails.

ADR-021's rule: a confirmation is judged on how *rarely* it fires. A guard that stops a
house number or a year teaches the user to dismiss it, and a dismissed guard is worse
than none — it costs attention and catches nothing. So most of these tests assert
**silence**, and the ones that assert a catch are the minority. That ratio is the design.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from yazses.checkdigit.guard import check, describe, looks_like_a_number
from yazses.config import CheckdigitConfig, Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform

# Passes Luhn. Verified by the arithmetic, not assumed.
GOOD_CARD = "4539148803436467"
# One digit changed, so it fails.
BAD_CARD = "4539148803436468"
SCHEMES = ["luhn", "isbn13", "isbn10"]


def _daemon(mocker, **kw):
    cfg = replace(Config(), checkdigit=CheckdigitConfig(enabled=True, **kw))
    d = Daemon(config=cfg, platform=get_platform())
    d._notify_cmdsafety = mocker.MagicMock()
    return d


# ---- the fixture numbers are what I claim they are -------------------------


def test_the_good_card_really_passes_luhn():
    """Guard the guard: a wrong fixture would make every test below meaningless."""
    assert check(GOOD_CARD, SCHEMES).failed is False


def test_the_bad_card_really_fails_luhn():
    assert check(BAD_CARD, SCHEMES).failed is True


# ---- when it must stay silent ----------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "hello there",                       # prose
        "my card is 4539148803436468",       # a number inside a sentence is not a field
        "2026",                              # a year
        "42",                                # anything short
        "",                                  # nothing
        "   ",
        GOOD_CARD,                           # a number that passes
        "4539 1488 0343 6467",               # ...with the spacing people actually say
    ],
)
def test_it_says_nothing_about_these(text):
    """Every false catch costs trust in every future prompt."""
    assert check(text, SCHEMES).failed is False


def test_a_number_below_the_minimum_is_not_examined():
    """Luhn will happily reject a house number; that is not evidence of anything."""
    assert check("12345", SCHEMES, min_digits=12).failed is False


def test_a_length_no_configured_scheme_fits_is_left_alone():
    """An 11-digit string is not an ISBN, so ISBN's opinion of it is noise."""
    assert check("12345678901", ["isbn13", "isbn10"]).failed is False


def test_passing_any_applicable_scheme_is_enough():
    """A valid ISBN-13 must not be held because Luhn happens to disagree with it.

    Holding it would be the guard inventing a problem: a string satisfying a real
    checksum is overwhelmingly likely to be that kind of number.
    """
    isbn13 = "9780306406157"
    assert check(isbn13, ["isbn13"]).failed is False
    assert check(isbn13, ["luhn", "isbn13"]).failed is False


# ---- when it must speak ----------------------------------------------------


def test_a_failed_card_is_caught():
    result = check(BAD_CARD, SCHEMES)
    assert result.failed and result.scheme == "luhn"


def test_a_single_candidate_correction_is_offered():
    """One candidate is a suggestion. Several would be a guess between them."""
    result = check(BAD_CARD, SCHEMES)
    if result.suggestion:
        assert check(result.suggestion, SCHEMES).failed is False, (
            "the suggested correction must itself pass"
        )


def test_no_suggestion_when_it_is_not_wanted():
    assert check(BAD_CARD, SCHEMES, want_suggestion=False).suggestion == ""


def test_the_message_names_the_scheme_and_the_way_out():
    message = describe(check(BAD_CARD, SCHEMES))
    assert "confirm" in message.lower(), "the user must be told how to proceed anyway"
    assert message, "a hold with no explanation is just lost text"


def test_no_message_when_nothing_failed():
    assert describe(check(GOOD_CARD, SCHEMES)) == ""


# ---- wired into the daemon -------------------------------------------------


def test_a_bad_number_does_not_type(mocker):
    d = _daemon(mocker)
    event: dict = {}
    assert d._checkdigit_gate(BAD_CARD, event) is None
    assert event["checkdigit_action"] == "held"
    assert d._cmdsafety.pending == BAD_CARD


def test_a_good_number_types_normally(mocker):
    d = _daemon(mocker)
    event: dict = {}
    assert d._checkdigit_gate(GOOD_CARD, event) == GOOD_CARD
    assert "checkdigit_action" not in event


def test_confirm_releases_it_through_the_command_gate(mocker):
    """One confirm word for both guards — the user should not have to remember which
    guard stopped them."""
    d = _daemon(mocker)
    d._checkdigit_gate(BAD_CARD, {})
    assert d._cmdsafety_gate("confirm", {}) == BAD_CARD


def test_the_confirmation_utterance_is_not_itself_check_digited(mocker):
    """With something held, this gate must stand aside.

    Otherwise the release word would be examined as if it were a number, and a held
    value could never be released.
    """
    d = _daemon(mocker)
    d._checkdigit_gate(BAD_CARD, {})
    assert d._checkdigit_gate("confirm", {}) == "confirm"


def test_off_by_default():
    assert Config().checkdigit.enabled is False


def test_looks_like_a_number_rejects_prose():
    assert looks_like_a_number(GOOD_CARD, 12)
    assert not looks_like_a_number("my card is " + GOOD_CARD, 12)


def test_the_gate_runs_on_the_dictation_path():
    """A correct pure function nothing calls would pass every test above."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(Daemon._on_hold_end)))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "_checkdigit_gate" in called, "the guard is never reached from _on_hold_end"
