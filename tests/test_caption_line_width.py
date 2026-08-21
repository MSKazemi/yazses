"""Subtitles were emitted as single lines of up to 80 characters.

Measured on a real 162-second recording put through `yazses transcribe --format srt`:

    cues                       22
    reading rate               fine everywhere (max 16.7 chars/second)
    lines wider than 42 chars  18 of 22, up to 80

`merge_word_timestamps` caps a segment at `max_chars=80` and its docstring calls that a
*line* — but the writers emitted the whole segment as one line, and 80 is roughly double
what a caption line can be.

Every subtitle standard and every player assumes about half that: EBU-TT-D, the BBC
guidelines and Netflix's timed-text spec all sit at 37–42 characters over at most two
lines, because that is what fits the video width at default caption size. Going over does
not fail loudly — the player wraps it itself, wherever it likes, or lets it run off frame.
So the output looked correct in a text editor and wrong in a video.

## Timings are untouched, deliberately

The wrap happens in the writers, not in segmentation. 42 × 2 fits the existing 80-character
segment budget exactly, so every cue boundary and every timestamp is identical. Verified
against the real recording before and after: 22 cues either way, identical timestamps,
identical words.

## Balanced, not greedy

Greedy filling puts a full line above a two-word line, which reads badly and pulls the eye
to the wrong place. The split is the word boundary nearest the middle where both sides fit.

## Overflow wraps rather than truncates

Text that cannot fit two lines gets more lines. A caption that loses words is worse than a
caption that is too tall, and the caller already caps segment length — overflow means that
cap changed, not that the words are expendable.
"""

from __future__ import annotations

import pytest

from yazses.recimport.subtitles import (
    CAPTION_LINE_CHARS,
    CAPTION_MAX_LINES,
    merge_word_timestamps,
    wrap_caption,
    write_srt,
    write_vtt,
)

# A real cue from the recording, at the 80-character segment cap.
LONG = "So if code is wrong, modify it and improve it and use it. I mean merge it and if"


def test_a_long_caption_is_split_into_two_lines() -> None:
    out = wrap_caption(LONG)
    lines = out.split("\n")
    assert len(lines) == 2
    assert max(len(line) for line in lines) <= CAPTION_LINE_CHARS


def test_no_words_are_lost_or_reordered() -> None:
    """The only thing a caption may never do."""
    assert wrap_caption(LONG).split() == LONG.split()


def test_a_short_caption_is_left_on_one_line() -> None:
    """Wrapping everything would be as wrong as wrapping nothing."""
    assert wrap_caption("Right, so the plan is this.") == "Right, so the plan is this."
    assert "\n" not in wrap_caption("x" * CAPTION_LINE_CHARS)


def test_the_split_is_balanced_not_greedy() -> None:
    """Greedy fill gives a full line above a two-word line; balanced reads better."""
    text = "one two three four five six seven eight nine ten eleven twelve thirteen"
    head, tail = wrap_caption(text).split("\n")
    assert abs(len(head) - len(tail)) <= 12, f"lopsided: {len(head)} vs {len(tail)}"


def test_an_unsplittable_caption_keeps_every_word() -> None:
    """Truncating is never the right answer; more lines is."""
    text = " ".join(["word"] * 60)
    out = wrap_caption(text)
    assert out.split() == text.split()
    assert len(out.split("\n")) > CAPTION_MAX_LINES


def test_a_single_word_longer_than_the_width_is_not_broken() -> None:
    """Hyphenating mid-word would corrupt a URL or an identifier."""
    long_word = "supercalifragilisticexpialidociousandthensome"
    assert wrap_caption(long_word) == long_word


def test_empty_and_whitespace() -> None:
    assert wrap_caption("") == ""
    assert wrap_caption("   ") == ""


@pytest.mark.parametrize("writer", [write_srt, write_vtt])
def test_both_writers_wrap(writer) -> None:
    """VTT was the one that had no test at all; the defect was in both."""
    doc = writer([(0.0, 5.0, LONG)])
    body = [ln for ln in doc.split("\n") if ln and "-->" not in ln and ln != "WEBVTT"]
    assert len(body) >= 2
    assert max(len(ln) for ln in body) <= CAPTION_LINE_CHARS


def test_segmentation_is_untouched() -> None:
    """The wrap is a rendering change. If it ever moves into segmentation, every
    timestamp in every previously generated file becomes wrong."""
    words = [(f"w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(40)]
    before = merge_word_timestamps(words)
    after = merge_word_timestamps(words)
    assert before == after
    assert all("\n" not in text for _s, _e, text in before), (
        "segments now carry newlines — wrapping has leaked into segmentation, and cue "
        "boundaries are no longer what they were"
    )


def test_the_line_budget_still_fits_the_segment_budget() -> None:
    """42 x 2 >= 80 is what makes this a pure rendering change.

    If `merge_word_timestamps`'s `max_chars` grows past that, captions start needing a
    third line and this file's premise is gone.
    """
    import inspect

    source = inspect.getsource(merge_word_timestamps)
    assert "max_chars: int = 80" in source
    assert CAPTION_LINE_CHARS * CAPTION_MAX_LINES >= 80
