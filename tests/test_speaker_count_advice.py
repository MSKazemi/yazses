"""A hint whose own justification expired, and had to be re-measured rather than kept.

Meeting Mode ships `max_speakers = 0` (auto). Written against the old
`cluster_threshold = 0.5`, this hint was unarguable: on the AMI test split that pairing
scored **84.09% DER**, finding 257, 81, 86 and 98 speakers in four four-person meetings,
while setting the count to 4 scored **28.55%**.

ADR-v2-133 raised the defaults, and the ordering **reversed**. On the full 16-recording
AMI test split, auto-count at `1.2` scores **26.71%** and `max_speakers = 4` scores
**29.42%**. A hint still saying "this fixes most of it" would now be pushing users toward
the worse setting — the failure mode of every number written into prose and then left
there while the thing it described moved.

What survives is that the estimate is wrong in both directions without saying so: exact on
2 of 16 AMI meetings, and under-counting a crowded recording at the `[recimport]` default.
A user who *knows* the count can still delete that error term, and because `max_speakers`
is an exact count on this backend rather than a cap, a user who is guessing must not.

So both surfaces that begin a diarized run still say it *before* the run, not after — on a
long recording the advice is worth nothing once the decode has already happened — but they
say a different, smaller, true thing.

What is guarded here is when the hint must stay quiet, which is the half that decides
whether anyone reads it. It fires only when it can help: diarization on, the sherpa
backend, no count given. On pyannote the same field is a genuine upper bound and
leaving it unset is a reasonable default, so advising there would be wrong; with a
count already set there is nothing to say; and a hint that appears when diarization
is off is a hint the user learns to skip.
"""
from __future__ import annotations

import dataclasses

from yazses.config import MeetingConfig, RecimportConfig
from yazses.recimport.factory import speaker_count_advice

REMEDY = "Pass `--speakers N`."


def test_it_fires_on_the_shipped_defaults_because_that_is_the_broken_case():
    cfg = dataclasses.replace(RecimportConfig(), diarize=True)
    assert cfg.max_speakers == 0 and cfg.backend == "sherpa"
    hint = speaker_count_advice(cfg, REMEDY)
    assert hint is not None
    assert REMEDY in hint


def test_the_remedy_comes_from_the_caller_so_neither_surface_names_the_other_command():
    """`--speakers` does not exist in Meeting Mode and `[meeting] max_speakers` does
    not exist on the `transcribe` path; a shared sentence would send half the users
    to a setting they cannot reach."""
    cfg = dataclasses.replace(MeetingConfig(), diarize=True)
    meeting = speaker_count_advice(cfg, "Set `[meeting] max_speakers`.")
    transcribe = speaker_count_advice(cfg, REMEDY)
    assert meeting.endswith("Set `[meeting] max_speakers`.")
    assert transcribe.endswith(REMEDY)
    # The measured half is shared, which is the half that must not drift.
    shared = meeting[: -len("Set `[meeting] max_speakers`.")]
    assert shared and transcribe.startswith(shared)


def test_it_is_silent_once_a_count_is_given():
    cfg = dataclasses.replace(RecimportConfig(), diarize=True, max_speakers=4)
    assert speaker_count_advice(cfg, REMEDY) is None


def test_it_is_silent_when_speaker_labels_were_never_asked_for():
    cfg = dataclasses.replace(RecimportConfig(), diarize=False)
    assert speaker_count_advice(cfg, REMEDY) is None


def test_it_is_silent_on_pyannote_where_the_field_really_is_an_upper_bound():
    """The advice is backend-specific because the *behaviour* is: sherpa reads the
    value as an exact cluster count, pyannote as a cap."""
    cfg = dataclasses.replace(RecimportConfig(), diarize=True, backend="pyannote")
    assert speaker_count_advice(cfg, REMEDY) is None


def test_it_is_silent_on_a_backend_that_cannot_diarize_at_all():
    """`diarization_advice` already owns that case, and two messages about one fault
    is the shape this module's docstring exists to prevent."""
    cfg = dataclasses.replace(RecimportConfig(), diarize=True, backend="none")
    assert speaker_count_advice(cfg, REMEDY) is None


def test_the_backend_name_is_matched_loosely_like_every_other_read_of_it():
    cfg = dataclasses.replace(RecimportConfig(), diarize=True, backend="  Sherpa ")
    assert speaker_count_advice(cfg, REMEDY) is not None


def test_the_hint_quotes_the_measurement_rather_than_asserting_a_vibe():
    """"Accuracy may be lower" is advice nobody acts on. The number is what makes the
    difference legible — and it has to be a number that is still true."""
    cfg = dataclasses.replace(RecimportConfig(), diarize=True)
    hint = speaker_count_advice(cfg, REMEDY)
    assert "2 " in hint and "16" in hint, hint


def test_the_hint_no_longer_claims_the_flag_is_an_improvement():
    """The reversal is the point: at the shipped thresholds, pinning the count is 29.42%
    against auto's 26.71% on the AMI test split. A hint that still promised a large win
    would be recommending the worse of the two."""
    cfg = dataclasses.replace(RecimportConfig(), diarize=True)
    hint = speaker_count_advice(cfg, REMEDY).lower()
    for stale in ("257", "84%", "84 %", "over-splits badly"):
        assert stale not in hint, f"the hint still quotes the pre-ADR-v2-133 case: {stale}"


def test_the_hint_warns_that_the_count_is_exact_rather_than_a_maximum():
    """`max_speakers` becomes FastClusteringConfig(num_clusters=N) on the shipped
    backend, so a cautious over-estimate invents people. Advising a user to set it
    without saying that is advising them into a different bug."""
    cfg = dataclasses.replace(RecimportConfig(), diarize=True)
    hint = speaker_count_advice(cfg, REMEDY).lower()
    assert "exact count" in hint and "not a maximum" in hint
