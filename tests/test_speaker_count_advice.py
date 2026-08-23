"""The one setting worth more than all the others, and nothing said it.

Meeting Mode ships `max_speakers = 0` (auto) with `cluster_threshold = 0.5`. Measured
on the AMI test split — four real four-person meetings, headset mix, human RTTMs from
`pyannote/AMI-diarization-setup` — that combination scores **84.09% DER** and finds
257, 81, 86 and 98 speakers in the four meetings. Setting the count to 4 scores
**28.55%** with 4 of 4 speakers every time (ADR-v2-133).

A user who records an hour-long meeting gets an unreadable transcript, no error, and
no indication that a single number would have fixed most of it. So both surfaces that
begin a diarized run now say so *before* the run, not after: on a long recording the
advice is worth nothing once the decode has already happened.

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
    """"Accuracy may be lower" is advice nobody acts on. The numbers are what make
    the difference legible, and they are the reason the flag is worth a line."""
    cfg = dataclasses.replace(RecimportConfig(), diarize=True)
    hint = speaker_count_advice(cfg, REMEDY)
    assert "257" in hint and "84" in hint
