"""`yazses meeting relabel` re-cut the transcript it promised only to re-render.

Its own docstring says it re-renders "from ``transcript.json``, never re-diarizing", and
the CLI help says it "only re-renders". What it actually did was rebuild every utterance
from the stored **words** through `merge_utterances`, which is the *diarized* path's
segmentation rule -- so relabelling reshaped the transcript in two ways the finalize pass
had deliberately decided against.

**One.** `recimport/pipeline.py` calls `merge_utterances` only under `if diarized:`. A
non-diarized meeting gets exactly one utterance spanning the whole recording, on purpose:
with no speaker turns there is nothing to break a run on, and a silence gap is not a turn.
`relabel` called it unconditionally, so a non-diarized transcript came back gap-split on
the 1.0 s default. Measured on a real 11.6 s meeting on this machine: one utterance in,
two out. Every meeting in `yazses meeting list` there is non-diarized -- which is the
normal state without the diarization extra, and exactly the user who reaches for `relabel`
to put a name on an un-attributed transcript.

**Two.** The pipeline runs `clean_text` over the utterances and *drops* the ones that
clean to nothing, because Whisper narrates silence: an 11.6 s meeting of room noise
finalized as `". . ."`. `relabel` rebuilt from `words`, which the pipeline leaves
uncleaned on purpose ("timing data feeding alignment and subtitle spans"), and applied no
cleaning of its own -- so the artefacts the finalize pass had removed came back on the
first relabel.

Neither shows up as an error. The command prints the paths it wrote and exits 0.
"""
from __future__ import annotations

import json
from pathlib import Path

from yazses.meeting.store import relabel


def _write(meeting_dir: Path, *, diarized: bool, utterances, words, speakers=None) -> Path:
    meeting_dir.mkdir(parents=True, exist_ok=True)
    (meeting_dir / "transcript.json").write_text(
        json.dumps(
            {
                "language": "en",
                "diarized": diarized,
                "speakers": speakers or {},
                "text": " ".join(u["text"] for u in utterances),
                "utterances": utterances,
                "words": words,
            }
        ),
        encoding="utf-8",
    )
    return meeting_dir


def _utterances(meeting_dir: Path):
    data = json.loads((meeting_dir / "transcript.json").read_text(encoding="utf-8"))
    return data["utterances"]


# A pause longer than merge_utterances' 1.0 s default sits between the two halves --
# ordinary in speech, and not a speaker change.
_GAPPED_WORDS = [
    {"start": 0.0, "end": 0.4, "text": "hello", "speaker": None},
    {"start": 0.4, "end": 0.9, "text": "there", "speaker": None},
    {"start": 8.0, "end": 8.6, "text": "still", "speaker": None},
    {"start": 8.6, "end": 9.2, "text": "here", "speaker": None},
]


def test_a_non_diarized_transcript_keeps_its_single_utterance(tmp_path):
    """The finalize pass produces one utterance for an undiarized recording, on purpose."""
    d = _write(
        tmp_path / "m1",
        diarized=False,
        utterances=[{"speaker": "", "name": "", "start": 0.0, "end": 9.2,
                     "text": "hello there still here"}],
        words=_GAPPED_WORDS,
    )

    relabel(d, renames={"speaker_1": "Alice"})

    got = _utterances(d)
    assert len(got) == 1, f"the silence gap re-cut the transcript: {got}"
    assert got[0]["text"] == "hello there still here"


def test_whisper_artefacts_the_finalize_pass_dropped_do_not_come_back(tmp_path):
    """`words` are stored uncleaned by design, so rebuilding from them resurrects them."""
    d = _write(
        tmp_path / "m2",
        diarized=False,
        utterances=[{"speaker": "", "name": "", "start": 0.0, "end": 11.6, "text": "real speech"}],
        words=[
            {"start": 0.0, "end": 0.5, "text": ".", "speaker": None},
            {"start": 0.5, "end": 1.0, "text": "real", "speaker": None},
            {"start": 1.0, "end": 1.5, "text": "speech", "speaker": None},
            {"start": 10.5, "end": 11.6, "text": "[BLANK_AUDIO]", "speaker": None},
        ],
    )

    relabel(d, renames={"speaker_1": "Alice"})

    text = " ".join(u["text"] for u in _utterances(d))
    assert "[BLANK_AUDIO]" not in text, f"artefact resurrected: {text!r}"
    assert text.strip(". ") != "", "everything was dropped"


def test_an_all_artefact_transcript_relabels_to_nothing_rather_than_to_dots(tmp_path):
    """The real 11.6 s meeting on this machine: room noise Whisper narrated as ". . .".

    The finalize pass now drops utterances that clean to nothing. A relabel must not put
    them back as `". ."` and `"."`, which is what it did.
    """
    d = _write(
        tmp_path / "m3",
        diarized=False,
        utterances=[],
        words=[
            {"start": 0.0, "end": 0.54, "text": ".", "speaker": None},
            {"start": 0.54, "end": 1.06, "text": ".", "speaker": None},
            {"start": 10.48, "end": 11.56, "text": ".", "speaker": None},
        ],
    )

    relabel(d, renames={"speaker_1": "Alice"})

    assert _utterances(d) == [], f"artefacts came back: {_utterances(d)}"


def test_relabel_is_idempotent(tmp_path):
    """A command that reshapes on the first run and not the second is a command whose
    output depends on how many times you ran it."""
    d = _write(
        tmp_path / "m4",
        diarized=False,
        utterances=[{"speaker": "", "name": "", "start": 0.0, "end": 9.2,
                     "text": "hello there still here"}],
        words=_GAPPED_WORDS,
    )
    canon = d / "transcript.json"

    before = canon.read_text(encoding="utf-8")
    relabel(d, renames={"speaker_1": "Alice"})
    once = canon.read_text(encoding="utf-8")
    relabel(d, renames={"speaker_1": "Alice"})
    twice = canon.read_text(encoding="utf-8")

    assert once == twice, "second relabel changed the file again"
    assert json.loads(before)["utterances"] == json.loads(once)["utterances"]


# --- the feature itself must keep working -------------------------------------------


_DIARIZED_WORDS = [
    {"start": 0.0, "end": 0.5, "text": "hello", "speaker": "speaker_1"},
    {"start": 0.5, "end": 1.0, "text": "there", "speaker": "speaker_1"},
    {"start": 2.0, "end": 2.5, "text": "hi", "speaker": "speaker_2"},
    {"start": 2.5, "end": 3.0, "text": "back", "speaker": "speaker_2"},
]


def _diarized(tmp_path: Path) -> Path:
    return _write(
        tmp_path,
        diarized=True,
        utterances=[
            {"speaker": "speaker_1", "name": "Speaker 1", "start": 0.0, "end": 1.0, "text": "hello there"},
            {"speaker": "speaker_2", "name": "Speaker 2", "start": 2.0, "end": 3.0, "text": "hi back"},
        ],
        words=_DIARIZED_WORDS,
        speakers={"speaker_1": "Speaker 1", "speaker_2": "Speaker 2"},
    )


def test_renaming_a_diarized_speaker_still_works(tmp_path):
    d = _diarized(tmp_path / "m5")

    relabel(d, renames={"speaker_1": "Alice"})

    data = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    assert "Alice" in data["speakers"].values()


def test_merging_two_diarized_clusters_still_works(tmp_path):
    """The reason the command exists: an auto-count that split one person in two."""
    d = _diarized(tmp_path / "m6")

    relabel(d, merges={"speaker_2": "speaker_1"})

    data = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    speakers = {u["speaker"] for u in data["utterances"]}
    assert speakers == {"speaker_1"}, speakers


def test_a_diarized_relabel_does_not_resurrect_artefacts_from_the_words(tmp_path):
    """The diarized branch legitimately rebuilds utterances from `words` -- and `words`
    are stored uncleaned on purpose, so that branch is exactly where the artefacts the
    finalize pass dropped can come back.

    Written after a mutation test passed that should not have: removing the cleaning step
    broke nothing, because every fixture above stops the rebuild before it starts. The
    green mutation was the fixtures' fault, not the fix's.
    """
    d = _write(
        tmp_path / "m7",
        diarized=True,
        utterances=[
            {"speaker": "speaker_1", "name": "Speaker 1", "start": 0.0, "end": 1.0, "text": "hello there"},
        ],
        words=[
            {"start": 0.0, "end": 0.5, "text": "hello", "speaker": "speaker_1"},
            {"start": 0.5, "end": 1.0, "text": "there", "speaker": "speaker_1"},
            {"start": 30.0, "end": 32.0, "text": "[BLANK_AUDIO]", "speaker": "speaker_2"},
        ],
        speakers={"speaker_1": "Speaker 1", "speaker_2": "Speaker 2"},
    )

    relabel(d, renames={"speaker_1": "Alice"})

    data = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    texts = [u["text"] for u in data["utterances"]]
    assert not any("[BLANK_AUDIO]" in t for t in texts), f"artefact resurrected: {texts}"
    assert "hello there" in texts


def test_the_transcript_text_is_cleaned_like_the_finalize_pass_cleans_it(tmp_path):
    """Leaving `text` as ". . ." beside an empty utterance list is two answers to one
    question. The finalize pass runs `clean_text` over both."""
    d = _write(
        tmp_path / "m8",
        diarized=False,
        utterances=[],
        words=[{"start": 0.0, "end": 0.5, "text": ".", "speaker": None}],
    )
    # _write derives text from the utterances, so set the artefact text explicitly.
    canon = d / "transcript.json"
    data = json.loads(canon.read_text(encoding="utf-8"))
    data["text"] = "[BLANK_AUDIO]"
    canon.write_text(json.dumps(data), encoding="utf-8")

    relabel(d, renames={"speaker_1": "Alice"})

    assert json.loads(canon.read_text(encoding="utf-8"))["text"] == ""
