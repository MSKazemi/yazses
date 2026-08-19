"""A macro with two `${cursor}` markers typed one of them into the document.

`expand` positions the caret at the **first** `${cursor}` — which is documented — by
splitting the template there and measuring the tail. Any further markers stayed in that
tail and went straight to the injector:

    template  "a${cursor}b${cursor}c"
    typed     "ab${cursor}c"

`${cursor}` is not in `_VAR_NAMES`, so `_resolve_vars` leaves it alone by design (unknown
tokens are kept literal), and nothing else removed it. A user who wrote two markers — an
easy thing to do while editing a template — got the marker text in their document.

Stripping the extras before measuring the tail keeps the offset correct: the caret still
lands where the first marker was, now measured against the text actually injected rather
than against text containing a marker that will not be there.

`[macros] enabled` is off by default and templates are user-authored, so this reaches
whoever writes one.
"""

from __future__ import annotations

import pytest

from yazses.commands.macros import Macro, MacroContext, expand

CTX = MacroContext(clipboard="CLIP", date="2026-08-19", time="14:30", author="Mohsen")


def _expand(template: str) -> tuple[str, int]:
    return expand(Macro(trigger="t", type="text", template=template, actions=[]), CTX)


def _caret_position(template: str) -> tuple[str, int]:
    """(text, absolute caret index) — offset is measured back from the end."""
    text, offset = _expand(template)
    return text, len(text) - offset


@pytest.mark.parametrize(
    "template,expected",
    [
        ("a${cursor}b${cursor}c", "abc"),
        ("x${cursor}y${cursor}z${cursor}", "xyz"),
        ("${cursor}${cursor}only", "only"),
    ],
)
def test_a_marker_is_never_typed(template: str, expected: str) -> None:
    text, _ = _expand(template)
    assert "${cursor}" not in text, f"a cursor marker was injected: {text!r}"
    assert text == expected


def test_the_caret_still_lands_at_the_first_marker() -> None:
    """Stripping the extras must not shift the caret."""
    text, pos = _caret_position("a${cursor}b${cursor}c")
    assert text == "abc"
    assert pos == 1, f"caret at {pos} in {text!r}, expected just after 'a'"


@pytest.mark.parametrize(
    "template,text,pos",
    [
        ("def foo(${cursor})", "def foo()", 8),
        ("${author}: ${cursor} end", "Mohsen:  end", 8),
        ("${cursor}${author}", "Mohsen", 0),
    ],
)
def test_the_single_marker_cases_are_unchanged(template, text, pos) -> None:
    """These always worked; the fix must not disturb them."""
    got_text, got_pos = _caret_position(template)
    assert got_text == text
    assert got_pos == pos


def test_no_marker_means_no_offset() -> None:
    assert _expand("By ${author}") == ("By Mohsen", 0)
    assert _expand("plain text") == ("plain text", 0)


def test_an_unknown_variable_is_still_left_literal() -> None:
    """Documented behaviour, and deliberately different from `${cursor}`.

    An unknown `${...}` may be something the user meant to type; a *second* cursor marker
    is unambiguously a positioning directive that has already been honoured once.
    """
    assert _expand("Hi ${nope}") == ("Hi ${nope}", 0)
    assert _expand("${nope}${cursor}x") == ("${nope}x", 1)


def test_variables_still_resolve_on_both_sides_of_the_caret() -> None:
    text, pos = _caret_position("${author} ${cursor} ${date}")
    assert text == "Mohsen  2026-08-19"
    assert pos == 7
