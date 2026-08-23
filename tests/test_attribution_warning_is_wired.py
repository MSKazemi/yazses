"""The implausible-attribution warning has to reach a person, not just a log line.

The check itself is unit-tested in `test_diarization_plausibility.py`. What this file
guards is every seam between it and the user, because the failure it describes is
invisible by construction: the transcript is fluent, the timings are right, and the only
thing wrong is a number that looks like a fact about the meeting.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from yazses.recimport.pipeline import TranscriptResult, transcribe_file


@dataclass(frozen=True)
class Turn:
    start: float
    end: float
    speaker: str


class _Word:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


class _Engine:
    def transcribe_words(self, audio, sample_rate, task=None):
        return "hello there", [_Word(0.0, 1.0, "hello"), _Word(1.0, 2.0, "there")]


class _Diarizer:
    def __init__(self, turns):
        self._turns = turns

    def diarize(self, audio, sample_rate=16000):
        return self._turns


def _fragments(n: int) -> list[Turn]:
    """The measured AMI shape: five participant-sized labels and n-5 slivers."""
    turns, t = [], 0.0
    for i, secs in enumerate([60.0, 47.0, 46.0, 38.0, 37.0]):
        turns.append(Turn(t, t + secs, f"speaker_{i}"))
        t += secs
    for i in range(n - 5):
        turns.append(Turn(t, t + 5.0, f"speaker_{i + 5}"))
        t += 5.0
    return turns


def _run(turns, **kw):
    import numpy as np

    return transcribe_file(
        "x.wav",
        SimpleNamespace(model="tiny.en", language="en", min_speaker_seconds=3.0,
                        name_threshold=0.5),
        engine=_Engine(),
        diarizer=_Diarizer(turns),
        audio=np.zeros(16000, dtype="float32"),
        sample_rate=16000,
        **kw,
    )


def test_the_pipeline_sets_the_field_on_an_over_split_result():
    assert "86 speakers" in _run(_fragments(86)).attribution_suspect


def test_the_pipeline_leaves_it_empty_on_a_plausible_result():
    # The real IS1009a turn totals at cluster_threshold=1.2, measured on the AMI test
    # split: four speakers holding 412.7s, 165.3s, 73.8s and 35.6s. The smallest is the
    # one that matters -- it is the closest a genuine participant came to the floor.
    turns, t = [], 0.0
    for i, secs in enumerate([412.7, 165.3, 73.8, 35.6]):
        turns.append(Turn(t, t + secs, f"speaker_{i}"))
        t += secs
    assert _run(turns).attribution_suspect == ""


def test_an_undiarized_run_reports_nothing_rather_than_a_clean_bill():
    # No diarizer at all: the question was never asked, so answering it would assert
    # something no measurement supports.
    assert _run([]).attribution_suspect == ""


def test_the_field_defaults_empty_so_an_older_caller_still_constructs():
    r = TranscriptResult(text="", utterances=[], assigned=[], language="en",
                         diarized=False, speaker_names={})
    assert r.attribution_suspect == ""


def test_finalize_warns_without_suppressing_the_notes(monkeypatch, caplog):
    # The words are real; only the labels are wrong. Killing the minutes would destroy
    # the salvageable half of the output to hide the broken half.
    import yazses.meeting.finalize as fin

    result = TranscriptResult(
        text="hello", utterances=[SimpleNamespace(speaker="a", start=0, end=1, text="hi")],
        assigned=[], language="en", diarized=True, speaker_names={"a": "Speaker 1"},
        attribution_suspect="Speaker attribution looks unreliable: 86 speakers were found",
    )
    # finalize imports it inside the function, so the patch has to land on the
    # source module rather than on a name finalize does not hold.
    monkeypatch.setattr("yazses.recimport.pipeline.transcribe_file",
                        lambda *a, **k: result)
    called = []
    monkeypatch.setattr("yazses.meeting.notes.generate_minutes",
                        lambda *a, **k: called.append(1) or {"summary": "s"})
    with caplog.at_level("WARNING"):
        out = fin.finalize_meeting(
            [0.0], SimpleNamespace(notes=True, output_format="md"), sample_rate=16000,
        )
    assert called, "a suspect attribution must not suppress the minutes"
    assert out.minutes is not None
    assert "attribution looks unreliable" in caplog.text


@pytest.mark.parametrize(
    "meta,expected",
    [
        ({"num_speakers": 4}, "4 speaker(s)"),
        ({"num_speakers": 86, "attribution_suspect": ""}, "86 speaker(s)"),
        ({"num_speakers": 86, "attribution_suspect": "..."}, "86 speaker(s) — attribution unreliable"),
        # "unfinished" and "not diarized" answer a different question and must win: a
        # meeting that never finalized has no count to qualify.
        ({"recoverable": True, "attribution_suspect": "..."}, "unfinished"),
        ({"diarized": False, "attribution_suspect": "..."}, "not diarized"),
    ],
)
def test_the_shared_meeting_row_qualifies_a_suspect_count(meta, expected):
    from yazses.cli import _speaker_summary

    assert _speaker_summary(meta) == expected


def test_the_transcribe_cli_prints_the_note_and_names_the_remedy():
    # Read out of the source rather than driven end to end: the surrounding block needs
    # a decoded file. What can go wrong here is the note being dropped into the
    # if/elif chain above it, where an empty-transcript case would shadow it.
    import inspect

    import yazses.cli as cli

    src = inspect.getsource(cli.transcribe)
    assert "result.attribution_suspect" in src
    # The last split part: the name appears twice, in the `if` and in the message.
    assert "--speakers" in src.split("result.attribution_suspect")[-1][:600]
    # Parsed, not pattern-matched: what matters is that the note is a statement in the
    # function body rather than a branch of the empty/silent/no-speech chain above it,
    # and only the tree distinguishes those. An `elif` would make a suspect attribution
    # unreportable on any transcript that also tripped an earlier case.
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(src))
    fn = tree.body[0]
    tops = [
        n for n in fn.body
        if isinstance(n, ast.If) and "attribution_suspect" in ast.dump(n.test)
    ]
    assert len(tops) == 1, "the note must be its own `if` in the function body"


@pytest.mark.parametrize("module", ["controller", "recover"])
def test_both_meeting_writers_store_the_warning(module):
    # `meeting stop` returns long before finalize runs, so the stored meta is the only
    # surface left. A recovered meeting must not lose it either.
    import importlib
    import inspect

    src = inspect.getsource(importlib.import_module(f"yazses.meeting.{module}"))
    assert src.count('"attribution_suspect"') >= 2, "meta and the reply both carry it"
