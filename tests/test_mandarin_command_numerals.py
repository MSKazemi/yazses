"""Bounded Mandarin command numerals (#499, CMD-04 / CHN-22).

The parser is pure and deterministic: it accepts an explicit, closed set of forms
in an explicit range and refuses everything else. Two ranges exist — counts
(undo N times, delete/select the last N) stay at 0-99, line numbers reach 0-999 —
and the grammar's regex fragments must accept exactly what the parser accepts, or
a captured numeral could reach dispatch uninterpreted. The equivalence test below
proves that agreement on every string of up to five characters over the numeral
alphabet, which covers the longest valid form (九百九十九).
"""
from __future__ import annotations

import itertools
import re

import pytest

from yazses.commands import grammar as grammar_mod
from yazses.commands.grammar import IntentType, classify
from yazses.commands.grammars import zh
from yazses.commands.grammars.base import CommandGrammar, GrammarRule

_UNITS = "零一二三四五六七八九"


def _han(n: int, *, two: str = "二", zero: str = "零") -> str:
    """The standard written form of 0 <= n <= 999, as a native reader would expect."""
    if n < 10:
        return zero if n == 0 else _UNITS[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        head = "" if tens == 1 else _UNITS[tens]
        return head + "十" + ("" if ones == 0 else _UNITS[ones])
    hundreds, rest = divmod(n, 100)
    head = (two if hundreds == 2 else _UNITS[hundreds]) + "百"
    if rest == 0:
        return head
    if rest < 10:
        return head + zero + _UNITS[rest]
    tens, ones = divmod(rest, 10)
    # Inside a hundred the tens digit is always spoken: 一百一十, not 一百十.
    return head + _UNITS[tens] + "十" + ("" if ones == 0 else _UNITS[ones])


@pytest.mark.parametrize("n", range(0, 1000))
def test_every_standard_form_up_to_999_parses_to_its_value(n):
    assert zh.parse_command_number(_han(n)) == str(n)
    assert zh.parse_command_number(str(n)) == str(n)


@pytest.mark.parametrize("n", [200, 201, 210, 299])
@pytest.mark.parametrize("two", ["两", "兩"])
def test_liang_is_accepted_as_the_hundreds_multiplier(n, two):
    assert zh.parse_command_number(_han(n, two=two)) == str(n)


@pytest.mark.parametrize("n", [101, 205, 909])
def test_ling_and_circle_zero_are_equivalent_fillers(n):
    assert zh.parse_command_number(_han(n, zero="〇")) == str(n)


@pytest.mark.parametrize(
    "spoken",
    ["两", "兩", "〇", "１２３", " 一百 "],
)
def test_counting_two_full_width_digits_and_padding(spoken):
    assert zh.parse_command_number(spoken) is not None


@pytest.mark.parametrize(
    "spoken",
    [
        "",
        "百",            # no multiplier
        "十百",
        "一千",          # out of range, and 千 is not a supported form
        "一万",
        "1000",
        "一百一",        # elided colloquial 110: refused pending native review (#505)
        "两百五",        # elided colloquial 250
        "一百十",        # tens digit must be spoken inside a hundred
        "一百零",
        "一百零十",
        "一百零零五",
        "两十",          # 两 is not a tens multiplier
        "二十两",        # nor a units digit
        "一百零两",
        "零五",
        "二二",
        "一二三",        # digit-by-digit reading is not a number here
        "1百",           # mixed Arabic/Han
        "一2",
        "-1",
        "1.5",
        "٣",             # Arabic-Indic three: [0-9] is ASCII-explicit, unlike \d
        "三十三十",
    ],
)
def test_refuses_ambiguous_unbounded_or_non_standard_forms(spoken):
    assert zh.parse_command_number(spoken) is None


def test_explicit_ranges():
    assert zh.MAX_COUNT == 99
    assert zh.MAX_LINE_NUMBER == 999
    assert zh.parse_command_number("九十九", zh.MAX_COUNT) == "99"
    assert zh.parse_command_number("一百", zh.MAX_COUNT) is None
    assert zh.parse_command_number("100", zh.MAX_COUNT) is None
    assert zh.parse_number_0_99("九十九") == "99"
    assert zh.parse_number_0_99("一百") is None


def test_regex_fragments_accept_exactly_what_the_parser_accepts():
    alphabet = "零〇一二两兩三四五六七八九十百"
    count_re = re.compile(zh._COUNT)
    line_re = re.compile(zh._LINE)
    disagreements = []
    checked = 0
    candidates = itertools.chain(
        ("".join(t) for k in range(1, 6) for t in itertools.product(alphabet, repeat=k)),
        ("".join(t) for k in range(1, 5) for t in itertools.product("0123456789", repeat=k)),
    )
    for text in candidates:
        checked += 1
        if bool(count_re.fullmatch(text)) != (zh.parse_command_number(text, 99) is not None):
            disagreements.append(("count", text))
        if bool(line_re.fullmatch(text)) != (zh.parse_command_number(text, 999) is not None):
            disagreements.append(("line", text))
    assert checked > 800_000
    assert disagreements == []


@pytest.mark.parametrize("n", range(0, 1000))
def test_go_to_line_reaches_999_and_counts_stop_at_99(n):
    line = classify(f"转到第{_han(n)}行", language="zh")
    assert (line.action, line.args) == ("go_to_line", {"n": str(n)})

    delete = classify(f"删除最后{_han(n, two='两')}行", language="zh")
    if n == 1:
        # 删除最后一行 is the earlier no-count rule; dispatch defaults n to 1.
        assert (delete.action, delete.args) == ("delete_lines", {})
    elif n <= zh.MAX_COUNT:
        assert (delete.action, delete.args) == ("delete_lines", {"n": str(n)})
    else:
        assert delete.intent is IntentType.DICTATE


@pytest.mark.parametrize(
    "text",
    ["转到第一千行", "转到第1000行", "转到第一百一行", "转到第两十行", "删除最后二十两行"],
)
def test_out_of_range_or_malformed_numerals_stay_dictation(text):
    got = classify(text, language="zh")
    assert got.intent is IntentType.DICTATE
    assert got.action == "inject"


def test_an_argument_the_grammar_refuses_fails_closed_to_the_next_rule(monkeypatch):
    """normalise_arg returning None rejects the rule; raw text never reaches dispatch."""

    fake = CommandGrammar(
        language="xx",
        rules=(
            GrammarRule(re.compile(r"^go (.+)$"), IntentType.NAVIGATE, "go_to_line", ("n",)),
            GrammarRule(re.compile(r"^go (.+)$"), IntentType.EDIT, "fallback"),
        ),
        normalise=str.strip,
        normalise_arg=lambda _name, _value: None,
    )
    monkeypatch.setattr(grammar_mod, "get_grammar", lambda _language: fake)

    got = classify("go anywhere", language="xx")
    assert got.action == "fallback"
    assert got.args == {}

    only_rejecting = CommandGrammar(
        language="xx",
        rules=fake.rules[:1],
        normalise=str.strip,
        normalise_arg=lambda _name, _value: None,
    )
    monkeypatch.setattr(grammar_mod, "get_grammar", lambda _language: only_rejecting)
    assert classify("go anywhere", language="xx").intent is IntentType.DICTATE
