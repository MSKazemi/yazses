"""`--rename speaker_5=Bob` on a two-speaker recording renamed nobody and said nothing.

`resolve_names` returns a map documented as ``{canonical_speaker_id: display_name}``, and
it copied every rename into that map without checking the speaker exists. So a mistyped or
out-of-range id — `speaker_5` on a two-speaker file, or `Speaker_0` with the wrong case —
added a key naming nobody, which no renderer ever looks up.

The rename did nothing, reported nothing, and the transcript came back saying "Speaker 1".
The user is then left to work out whether diarization failed, whether the syntax was
wrong, or whether they miscounted the speakers.

Two changes, deliberately separate:

* the pure core no longer puts phantom ids in the map, which is just its own documented
  contract; and
* `unmatched_renames` names the keys that matched nothing, so `yazses transcribe` can say
  so — and can list the ids the recording *does* have, which is the thing the user needs
  and cannot otherwise discover without re-running.

The ids are `speaker_0`, `speaker_1`, … — `diarizer.py` builds them as
``f"speaker_{seg.speaker}"``, so the `--rename speaker_0=Alice` in the command's own help
is correct. That was checked, not assumed.
"""

from __future__ import annotations

import pytest

from yazses.recimport.align import Utterance
from yazses.recimport.naming import resolve_names, unmatched_renames

# spk1 speaks first — first-appearance order, not lexical.
UTTERANCES = [
    Utterance("spk1", 0.0, 5.0, "hello"),
    Utterance("spk0", 5.0, 9.0, "hi there"),
]


def test_a_rename_for_a_missing_speaker_is_not_in_the_map() -> None:
    """The contract: every key is a canonical speaker id from this recording."""
    result = resolve_names(UTTERANCES, renames={"ghost": "Nobody"})
    assert "ghost" not in result
    assert set(result) == {"spk0", "spk1"}


def test_a_real_rename_still_wins() -> None:
    """A fix that dropped renames entirely would pass the test above."""
    result = resolve_names(UTTERANCES, renames={"spk1": "Alice"})
    assert result["spk1"] == "Alice"
    assert result["spk0"] == "Speaker 1", "the other speaker still gets a fallback"


def test_a_rename_beats_a_positional_name() -> None:
    """Documented precedence, unchanged by the existence check."""
    result = resolve_names(UTTERANCES, names=["A", "B"], renames={"spk1": "Carol"})
    assert result == {"spk1": "Carol", "spk0": "B"}


@pytest.mark.parametrize(
    "renames,expected",
    [
        ({"ghost": "Nobody"}, ["ghost"]),
        ({"speaker_5": "Bob", "spk1": "Alice"}, ["speaker_5"]),
        ({"spk1": "Alice"}, []),
        ({}, []),
        (None, []),
        ({"ghost": "   "}, []),          # a blank name was never a rename
        ({"b": "X", "a": "Y"}, ["a", "b"]),  # sorted, for a stable message
    ],
)
def test_unmatched_renames_names_exactly_the_misses(renames, expected) -> None:
    assert unmatched_renames(UTTERANCES, renames) == expected


def test_case_matters_and_is_reported() -> None:
    """`Speaker_0` is not `speaker_0`; silently ignoring it is the whole complaint."""
    utterances = [Utterance("speaker_0", 0.0, 3.0, "hi")]
    assert unmatched_renames(utterances, {"Speaker_0": "Alice"}) == ["Speaker_0"]
    assert unmatched_renames(utterances, {"speaker_0": "Alice"}) == []


def test_the_cli_reports_it() -> None:
    """The message exists on the path a user actually takes.

    Read out of the source rather than run, because reaching it needs a real audio file
    and the optional diarization models. What matters is that the branch is wired to
    `unmatched_renames` at all — the pure behaviour is covered above.
    """
    import inspect

    from yazses import cli

    source = inspect.getsource(cli)
    assert "unmatched_renames" in source, "the CLI never asks which renames missed"
    assert "matched no speaker" in source, "the CLI computes the misses and says nothing"
