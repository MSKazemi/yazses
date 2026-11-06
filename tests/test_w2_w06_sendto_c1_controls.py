"""Send-to refuses C1 control characters, as ADR-031 says it refuses every control.

ADR-031 (design/adr/adr-031-send-to-prefill-handoff.md, "Limits (§4)") refuses "text
with control characters other than tab, newline and carriage return". Until this fix the
pure planner's pattern covered only C0 and DEL, so U+0080..U+009F — Unicode general
category ``Cc`` like the rest — were percent-encoded into the hand-off URL. U+009B is the
8-bit CSI that opens a terminal escape sequence; U+0085 (NEL) is a line break to some
renderers and invisible to others, so what the user reviews and what the agent reads can
differ. These tests fail on 8a72bbc6 and pass once the pattern covers the C1 range.
"""
from __future__ import annotations

import unicodedata

import pytest

from yazses.sendto.handoff import hand_off
from yazses.sendto.targets import Refusal, plan_handoff

C1_SAMPLES = ["\x80", "\x85", "\x8d", "\x9b", "\x9f"]


@pytest.mark.parametrize("target", ["claude", "claude-code", "codex"])
@pytest.mark.parametrize("ctrl", C1_SAMPLES)
def test_c1_control_inside_text_is_refused_not_encoded(target, ctrl):
    plan = plan_handoff(target, f"fix the bug{ctrl}then run the tests")
    assert plan.refusal is Refusal.INVALID_TEXT
    assert plan.url == ""
    assert "control characters" in plan.detail


def test_every_cc_character_except_tab_newline_cr_is_refused():
    """Derived from the Unicode database, not a hand-written set."""
    allowed = {"\t", "\n", "\r"}
    controls = [chr(cp) for cp in range(0x110000)
                if unicodedata.category(chr(cp)) == "Cc" and chr(cp) not in allowed]
    assert len(controls) == 62  # 32 C0 + DEL + 32 C1 = 65, minus tab, LF and CR
    for ctrl in controls:
        plan = plan_handoff("claude", f"a{ctrl}b")
        assert plan.refusal is Refusal.INVALID_TEXT, f"U+{ord(ctrl):04X} was not refused"


@pytest.mark.parametrize("ok_char", ["\xa0", "\xa9", "‌", "‏", " "])
def test_neighbours_of_the_c1_range_are_not_refused(ok_char):
    """NBSP, ©, ZWNJ (Persian orthography), RLM and LINE SEPARATOR are not ``Cc``."""
    plan = plan_handoff("claude", f"a{ok_char}b")
    assert plan.ok, plan.detail


def test_hand_off_never_calls_the_opener_for_c1_text_and_says_where_the_text_is():
    calls: list[str] = []

    def opener(url: str) -> bool:
        calls.append(url)
        return True

    result = hand_off("claude", "draft\x9b31mprompt", opener=opener, staged=True)
    assert calls == []
    assert result.ok is False
    assert result.reason == Refusal.INVALID_TEXT.value
    assert "still in the staged buffer" in result.message
    assert "draft" not in result.message
