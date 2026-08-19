"""A brace inside a summary must not throw the whole minutes away.

`_extract_json` pulls the first JSON object out of an LLM reply by counting braces. It
counted them blind, without tracking whether it was inside a string, so the first `}` in
any *value* closed the object early and `json.loads` failed on the fragment:

    {"summary": "the config needs a } here"}   ->  {}
    {"summary": "use { to open a block"}       ->  {}

Minutes of a technical meeting are exactly where a brace turns up in prose — a config
snippet, a code fragment, a bit of JSON someone read out. And the loss is silent:
`_parse_minutes` turns `{}` into an empty `Minutes`, so `yazses meeting notes` writes a
blank page and reports no error.

The scanner now tracks string context and backslash escapes. Nesting, fenced replies and
surrounding prose all still work, and genuinely unparseable output still yields `{}`
rather than a guess.

## Why not just `json.loads` the whole reply

Because it usually is not the whole reply. Local models wrap the object in ``` fences, or
prefix it with "Sure, here you go:" — which is what this function exists to survive. The
grammar-constrained path (`minutes_gbnf`) avoids that, but it is optional
(`[meeting] notes_grammar`), so this tolerant path is what runs by default.
"""

from __future__ import annotations

import pytest

from yazses.meeting.notes import _extract_json, _parse_minutes


@pytest.mark.parametrize(
    "reply,expected_summary",
    [
        pytest.param('{"summary": "we agreed"}', "we agreed", id="plain"),
        pytest.param(
            '```json\n{"summary": "we agreed"}\n```', "we agreed", id="fenced"
        ),
        pytest.param(
            'Sure! {"summary": "we agreed"} Hope that helps.', "we agreed", id="prose"
        ),
        pytest.param(
            '{"summary": "the config needs a } here"}',
            "the config needs a } here",
            id="close-brace-in-value",
        ),
        pytest.param(
            '{"summary": "use { to open a block"}',
            "use { to open a block",
            id="open-brace-in-value",
        ),
        pytest.param(
            '{"summary": "write {\\"a\\": 1} in the file"}',
            'write {"a": 1} in the file',
            id="json-quoted-inside-a-value",
        ),
        pytest.param(
            '{"summary": "he said \\"yes\\" firmly"}',
            'he said "yes" firmly',
            id="escaped-quotes",
        ),
    ],
)
def test_the_object_survives_whatever_is_in_its_strings(reply, expected_summary) -> None:
    assert _extract_json(reply).get("summary") == expected_summary


def test_nesting_still_works() -> None:
    assert _extract_json('{"summary": "x", "a": {"b": 1}}') == {
        "summary": "x",
        "a": {"b": 1},
    }


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param("I could not produce minutes.", id="no-json"),
        pytest.param('{"summary": "unfinished', id="truncated"),
        pytest.param("", id="empty"),
        pytest.param("{not json at all}", id="braces-but-not-json"),
    ],
)
def test_unusable_output_still_yields_nothing(reply) -> None:
    """A tolerant parser must stay honest — no guessing a summary out of prose."""
    assert _extract_json(reply) == {}


def test_the_whole_minutes_were_lost_not_just_the_summary() -> None:
    """Why this mattered: one brace emptied every field."""
    reply = (
        '{"summary": "we discussed the } in the config", '
        '"decisions": ["ship on Friday"], '
        '"action_items": [{"owner": "Alice", "task": "update the docs"}]}'
    )
    minutes = _parse_minutes(reply)
    assert minutes.summary == "we discussed the } in the config"
    assert minutes.decisions == ["ship on Friday"]
    assert [(a.owner, a.task) for a in minutes.action_items] == [
        ("Alice", "update the docs")
    ]


def test_a_blank_reply_gives_empty_minutes_without_raising() -> None:
    """The failure path must stay a quiet empty, not an exception into the post-pass."""
    minutes = _parse_minutes("nothing useful here")
    assert minutes.summary == ""
    assert minutes.decisions == []
    assert minutes.action_items == []
    assert minutes.per_speaker == []
