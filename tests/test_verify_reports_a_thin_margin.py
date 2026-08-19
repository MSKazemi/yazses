"""`verify` knew how loud the room was and never said it was barely loud enough.

The third fault in the same family as `test_verify_silence_verdict.py`. Run for real in
a quiet room, four times in a row, against a 0.0040 gate:

    level 0.0052 -> "I thought I was going to say the same thing before."   [OK]
    level 0.0054 -> "I just want you to know that it's your fault."          [OK]
    level 0.0060 -> "Okay. It's going to be fine."                           [OK]
    level 0.0052 -> ". . . . . . ."                                          [FAIL]

Only the fourth was caught, and only because `clean_text` empties a string of dots. The
other three are ordinary English: not a ghost phrase, not a repetition loop, not blank.
Nothing downstream can distinguish them from speech, and this module argues at length
that it must not try -- a verify that wrongly fails sends someone to re-calibrate a
microphone that was fine.

But the level was in front of it the whole time. `0.0052` against a `0.0040` gate is
1.3x, and that is a **measurement**, not a judgement about the words. It is also the fact
that makes the sentence interpretable: the difference between "my microphone is broken"
and "my gate is too low" is exactly this number, and the user was never shown it.

The margin comes from the daemon's own log rather than taste -- 172 real bursts, the
quietest one that produced *any* text sat at 0.0081 against the same 0.0040 gate, so 2x
is where speech starts. At 2x the note would have covered 26 of the 41 bursts that
decoded to nothing and **none** of the 131 that produced text.
"""

from __future__ import annotations

from yazses.system.verify import signal_detail, verify

GATE = 0.0040


def test_a_comfortable_level_says_nothing_extra():
    """Ordinary speech must not collect a warning, or the warning stops being read.

    0.0549 is the median level of a text-producing burst in the measured log.
    """
    detail = signal_detail(0.0549, GATE)
    assert detail == f"level 0.0549 clears the gate ({GATE:.4f})"


def test_a_thin_margin_names_the_multiple_and_the_fix():
    detail = signal_detail(0.0052, GATE)
    assert "1.3x" in detail, f"the user needs the number, not an adjective — got {detail!r}"
    assert "yazses mic-level --set" in detail, "a warning with no fix is a warning to dismiss"


def test_the_boundary_is_clear_not_thin():
    """Exactly 2x is where speech starts in the measured data, so it is not a warning."""
    assert signal_detail(GATE * 2, GATE) == f"level {GATE * 2:.4f} clears the gate ({GATE:.4f})"
    assert "only just" in signal_detail(GATE * 2 - 0.0001, GATE)


def test_a_disabled_gate_neither_divides_nor_warns():
    """`vad_threshold = 0` disables the gate, and nothing is barely above nothing.

    There is no zero-check in the function. Multiplying the threshold up is what makes
    this safe; dividing the level down -- the shape the ratio in the message invites,
    since the message quotes `level / threshold` -- raises on the same input. This test
    is the only thing standing between those two spellings.
    """
    assert signal_detail(0.0052, 0.0) == "level 0.0052 clears the gate (0.0000)"
    assert signal_detail(0.0, 0.0) == "level 0.0000 clears the gate (0.0000)"


def test_the_step_still_passes():
    """The gate genuinely was cleared, and this module's asymmetry runs one way.

    A verify that wrongly *passes* costs one confusing session; a verify that wrongly
    *fails* sends someone to re-calibrate a microphone that was fine. A thin margin is a
    caveat on a true statement, not a broken link -- so the chain must keep running and
    the transcript must still reach the screen, which is the only thing that can settle
    whether the words were real.
    """
    result = verify(
        record=lambda: object(),
        level_of=lambda _a: 0.0052,
        threshold=GATE,
        transcribe=lambda _a: "Okay. It's going to be fine.",
    )
    signal = next(s for s in result.steps if s.name == "Signal")
    assert signal.ok is True
    assert "only just" in signal.detail
    assert result.ok, "a thin margin must not be reported as the broken link"
    assert any(s.name == "Transcription" and s.ok for s in result.steps)
