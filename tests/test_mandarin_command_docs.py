"""The published Mandarin command table is the grammar, and it says it is unreviewed (#499).

``docs/use-cases/chinese-voice-typing.md`` is the page a Mandarin user reads. Its phrase
table is checked in both directions: every shipped action has a row, every phrase in a
row really is that command, and no row names an action the grammar does not ship. The
section must also carry each action's native-review state from ``zh.PHRASE_REVIEW``
and must not call the commands "supported" while nothing has been natively reviewed
(CMD-08 / #505).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from yazses.commands.grammar import IntentType, classify
from yazses.commands.grammars import zh

PAGE = Path(__file__).resolve().parent.parent / "docs" / "use-cases" / "chinese-voice-typing.md"
HEADING = "## Chinese voice commands"

#: How the page words each review state.
REVIEW_WORDING = {zh.REVIEW_PROVISIONAL: "unreviewed", zh.REVIEW_NATIVE: "native-reviewed"}


def _section() -> str:
    text = PAGE.read_text(encoding="utf-8")
    start = text.index(HEADING)
    end = text.find("\n## ", start + len(HEADING))
    return text[start : end if end != -1 else len(text)]


def _rows() -> dict[str, tuple[list[str], list[str], str]]:
    rows: dict[str, tuple[list[str], list[str], str]] = {}
    for line in _section().splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        assert len(cells) == 4, line
        action = re.findall(r"`([^`]+)`", cells[0])[0]
        assert action not in rows, f"duplicate row for {action}"
        rows[action] = (
            re.findall(r"`([^`]+)`", cells[1]),
            re.findall(r"`([^`]+)`", cells[2]),
            cells[3],
        )
    return rows


def test_table_has_exactly_one_row_per_shipped_action():
    assert set(_rows()) == set(zh.SAFE_CORE_ACTIONS)


def test_every_row_lists_a_simplified_and_a_traditional_phrase():
    thin = [a for a, (simp, trad, _) in _rows().items() if not simp or not trad]
    assert thin == []


@pytest.mark.parametrize("action", sorted(zh.SAFE_CORE_ACTIONS))
def test_every_documented_phrase_is_that_command(action):
    simp, trad, _ = _rows()[action]
    wrong = []
    for phrase in simp + trad:
        got = classify(phrase, language="zh")
        if got.intent is IntentType.DICTATE or got.action != action:
            wrong.append((phrase, got.action))
    assert wrong == []


def test_every_row_states_its_native_review_state():
    wrong = {
        action: review
        for action, (_, _, review) in _rows().items()
        if review != REVIEW_WORDING[zh.PHRASE_REVIEW[action]]
    }
    assert wrong == {}


def test_section_does_not_call_unreviewed_commands_supported():
    section = _section()
    assert "experimental" in section.lower()
    if set(zh.PHRASE_REVIEW.values()) == {zh.REVIEW_PROVISIONAL}:
        claims = [
            m.group(0)
            for m in re.finditer(r"(?i)(?:\bnot\s+|un)?supported\b", section)
            if not m.group(0).lower().startswith(("not", "un"))
        ]
        assert claims == []
        assert "native" in section.lower()


def test_section_says_how_to_turn_mandarin_commands_off():
    section = _section()
    assert 'language = "en"' in section
    assert "enabled = false" in section


def test_pinning_english_really_turns_every_documented_mandarin_phrase_into_text():
    """The page's off switch: under the English grammar no Mandarin phrase is a command."""
    fired = [
        (phrase, classify(phrase, language="en").action)
        for simp, trad, _ in _rows().values()
        for phrase in simp + trad
        if classify(phrase, language="en").intent is not IntentType.DICTATE
    ]
    assert fired == []
