"""A caption must never span a speaker change, and a diarized one must say who spoke.

`_render_subtitles` threw the speaker away:

    triples = [(text, start, end) for (_spk, start, end, text) in result.assigned]

and segmented on silence and line length alone, so two people's words landed in one
caption with no label:

    00:00:00,000 --> 00:00:04,000
    hello there hi          <- Alice's words and Bob's, together, unattributed

Two faults, and the second is the serious one. The missing label is a loss. The **merge**
makes the caption assert something untrue — that one person said all of it — and a
subtitle file is read by people who were not in the room and have no way to tell.

`render.py`'s own module docstring names this exact failure mode as the thing to avoid:
*"Speaker-tagged `txt` always carries labels when diarized — never silently dropped
(WhisperX's documented bug)"*. The promise was kept for `txt`, `md` and `json`, and
broken for `srt` and `vtt`.

Segments are now built per contiguous speaker run, so a caption cannot straddle a change,
and each is prefixed with the display name when diarized. Undiarized output is untouched —
its captions have no speaker to name.
"""

from __future__ import annotations

import pytest

from yazses.recimport.align import Utterance
from yazses.recimport.pipeline import TranscriptResult
from yazses.recimport.render import render_transcript


def _result(*, diarized: bool):
    if not diarized:
        return TranscriptResult(
            text="hello there hi",
            utterances=[Utterance("", 0.0, 4.0, "hello there hi")],
            assigned=[("", 0.0, 1.0, "hello"), ("", 1.0, 2.0, "there"), ("", 2.0, 4.0, "hi")],
            language="en", diarized=False, speaker_names={}, silent_input=False,
        )
    return TranscriptResult(
        text="hello there hi",
        utterances=[Utterance("speaker_0", 0.0, 2.0, "hello there"),
                    Utterance("speaker_1", 2.0, 4.0, "hi")],
        assigned=[("speaker_0", 0.0, 1.0, "hello"),
                  ("speaker_0", 1.0, 2.0, "there"),
                  ("speaker_1", 2.0, 4.0, "hi")],
        language="en", diarized=True,
        speaker_names={"speaker_0": "Alice", "speaker_1": "Bob"},
        silent_input=False,
    )


@pytest.mark.parametrize("fmt", ["srt", "vtt"])
def test_a_caption_never_spans_a_speaker_change(fmt: str) -> None:
    out = render_transcript(_result(diarized=True), fmt)
    lines = [ln for ln in out.splitlines() if "hello" in ln or "hi" in ln]
    assert lines, f"no caption text found in:\n{out}"
    for line in lines:
        assert not ("hello" in line and line.rstrip().endswith("hi")), (
            f"two speakers merged into one caption: {line!r}"
        )


@pytest.mark.parametrize("fmt", ["srt", "vtt"])
def test_a_diarized_caption_names_the_speaker(fmt: str) -> None:
    out = render_transcript(_result(diarized=True), fmt)
    assert "Alice:" in out and "Bob:" in out, (
        f"speaker labels silently dropped — the bug this module's docstring cites:\n{out}"
    )


@pytest.mark.parametrize("fmt", ["srt", "vtt"])
def test_an_undiarized_transcript_is_unchanged(fmt: str) -> None:
    """Nothing to attribute, so nothing may be prefixed."""
    out = render_transcript(_result(diarized=False), fmt)
    assert "hello there hi" in out
    assert ":" in out, "timestamps still present"
    for line in out.splitlines():
        assert not line.strip().startswith(": "), f"empty label prefixed: {line!r}"


def test_the_timings_still_bound_each_speakers_words() -> None:
    """Splitting must not lose or shift a boundary."""
    out = render_transcript(_result(diarized=True), "srt")
    assert "00:00:00,000 --> 00:00:02,000" in out, "Alice's run"
    assert "00:00:02,000 --> 00:00:04,000" in out, "Bob's run"


def test_the_other_formats_still_carry_labels() -> None:
    """They always did; a regression here would be the fix reaching too far."""
    res = _result(diarized=True)
    assert "Alice: hello there" in render_transcript(res, "txt")
    assert "Alice" in render_transcript(res, "md")
    assert '"name": "Alice"' in render_transcript(res, "json")


def test_a_speaker_returning_later_gets_separate_captions() -> None:
    """A→B→A must be three runs, not two merged ones."""
    res = TranscriptResult(
        text="one two three",
        utterances=[],
        assigned=[("speaker_0", 0.0, 1.0, "one"),
                  ("speaker_1", 1.0, 2.0, "two"),
                  ("speaker_0", 2.0, 3.0, "three")],
        language="en", diarized=True,
        speaker_names={"speaker_0": "Alice", "speaker_1": "Bob"}, silent_input=False,
    )
    out = render_transcript(res, "srt")
    assert out.count("Alice:") == 2, out
    assert out.count("Bob:") == 1, out
