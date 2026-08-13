"""Staged dictation: speak → review → commit (#294).

The feature exists because a mis-transcribed token in a terminal is a command you
did not mean to run. So the tests are mostly about the two ways that promise can be
broken: text reaching the app before the user approved it, and text the user staged
going missing.
"""

from __future__ import annotations

import pytest

from yazses.staged.buffer import (
    StagedAction,
    StagedBuffer,
    classify,
    describe,
    join_chunks,
)

# ---- the buffer ------------------------------------------------------------


def test_a_fresh_buffer_is_empty():
    buffer = StagedBuffer()
    assert buffer.is_empty
    assert buffer.text == ""


def test_bursts_accumulate_in_the_order_they_were_spoken():
    buffer = StagedBuffer()
    buffer.stage("git checkout")
    buffer.stage("minus b feature")
    assert buffer.text == "git checkout minus b feature"


def test_bursts_are_spaced_the_way_typing_them_would_have_been():
    """Staged text must read identically to the same words dictated unstaged."""
    assert join_chunks(["hello", "world"]) == "hello world"
    assert join_chunks(["hello", ", world"]) == "hello, world"
    assert join_chunks(["done", "."]) == "done."


def test_a_blank_burst_is_not_a_chunk():
    """Otherwise "scratch that" would silently remove nothing."""
    buffer = StagedBuffer()
    buffer.stage("real text")
    buffer.stage("   ")
    buffer.stage("")
    assert len(buffer.chunks) == 1
    assert buffer.undo() is True
    assert buffer.is_empty


# ---- commit ----------------------------------------------------------------


def test_commit_hands_back_the_text_and_empties_the_buffer():
    buffer = StagedBuffer()
    buffer.stage("rm minus rf slash tmp slash cache")
    result = buffer.commit()
    assert result.committed
    assert result.text == "rm minus rf slash tmp slash cache"
    assert buffer.is_empty, "committing twice must not type it twice"


def test_committing_nothing_is_distinguishable_from_typing_nothing():
    """One deserves a message; the other is a bug. They must not look alike."""
    result = StagedBuffer().commit()
    assert result.committed is False
    assert result.is_empty
    assert result.text == ""


# ---- discard and undo ------------------------------------------------------


def test_undo_removes_exactly_the_last_burst():
    """Which is what "scratch that" means, and what one joined string cannot do."""
    buffer = StagedBuffer()
    buffer.stage("keep this")
    buffer.stage("but not this")
    assert buffer.undo() is True
    assert buffer.text == "keep this"


def test_undo_on_an_empty_buffer_reports_that_it_did_nothing():
    assert StagedBuffer().undo() is False


def test_discard_returns_what_was_thrown_away():
    """So the notification can say how much, rather than "discarded."."""
    buffer = StagedBuffer()
    buffer.stage("three whole words")
    discarded = buffer.discard()
    assert len(discarded.split()) == 3
    assert buffer.is_empty


# ---- the grammar: this is where the feature can be defeated -----------------


def test_with_spoken_commands_off_nothing_can_commit_by_voice():
    """The default. A spoken commit can be produced by a mis-transcription."""
    for utterance in ("commit", "commit that", "send it", "discard that"):
        assert classify(utterance, spoken_commands=False) is StagedAction.STAGE


def test_undo_is_recognised_even_with_spoken_commands_off():
    """It only ever removes pending text, so a false positive costs a sentence."""
    assert classify("scratch that", spoken_commands=False) is StagedAction.UNDO


def test_a_spoken_commit_is_recognised_when_asked_for():
    for utterance in ("commit", "commit that", "commit it", "send it", "type it"):
        assert classify(utterance, spoken_commands=True) is StagedAction.COMMIT


def test_a_spoken_discard_is_recognised_when_asked_for():
    for utterance in ("discard", "discard that", "throw it away", "clear the buffer"):
        assert classify(utterance, spoken_commands=True) is StagedAction.DISCARD


@pytest.mark.parametrize("utterance", [
    "git commit minus m fix the parser",
    "then commit that change to the branch",
    "I will commit it later",
    "we should discard that approach",
    "let me type it out first",
])
def test_the_command_words_inside_a_sentence_are_staged_not_obeyed(utterance):
    """The grammar is anchored at both ends, like commands/revise.py.

    A suffix match would turn "git commit" into a commit — typing the buffer into
    a terminal, which is the exact accident staged mode was turned on to prevent.
    """
    assert classify(utterance, spoken_commands=True) is StagedAction.STAGE


def test_trailing_punctuation_does_not_defeat_the_grammar():
    """Whisper punctuates; "Commit that." is still a commit."""
    assert classify("Commit that.", spoken_commands=True) is StagedAction.COMMIT
    assert classify("  commit that  ", spoken_commands=True) is StagedAction.COMMIT


def test_case_does_not_matter():
    assert classify("SEND IT", spoken_commands=True) is StagedAction.COMMIT


# ---- what the user sees ----------------------------------------------------


def test_the_preview_keeps_the_end_because_that_is_what_you_just_said():
    buffer = StagedBuffer()
    buffer.stage("x" * 400)
    buffer.stage("the words I am checking")
    preview = buffer.preview(max_chars=40)
    assert preview.startswith("…"), "an ellipsis says plainly there is more above"
    assert preview.endswith("the words I am checking")
    assert len(preview) == 40


def test_a_short_buffer_is_shown_whole():
    buffer = StagedBuffer()
    buffer.stage("short")
    assert buffer.preview() == "short"


def test_the_summary_counts_words_and_bursts_and_says_what_to_do():
    buffer = StagedBuffer()
    buffer.stage("one two")
    buffer.stage("three")
    summary = describe(buffer)
    assert "3 words" in summary and "2 bursts" in summary
    assert "yazses staged commit" in summary


def test_the_summary_of_an_empty_buffer_does_not_invent_a_count():
    assert describe(StagedBuffer()) == "Staged mode: nothing pending."


def test_singulars_read_as_english():
    buffer = StagedBuffer()
    buffer.stage("word")
    assert "1 word pending in 1 burst" in describe(buffer)
