"""`yazses mic-level` calibrated to an empty room and said "recommended" anyway.

Run four times with nobody speaking:

    mean level:            0.0036 / 0.0044 / 0.0048 / 0.0050
    recommended:           0.002  / 0.0022 / 0.0024 / 0.0025

Every one of those recommendations is *below* the room noise that produced it. Applied with
`--set`, that is the state where room tone clears the gate, reaches the decoder, and comes
back as a confident invented word — the failure `yazses verify` was fixed for earlier the
same day.

Three of today's fixes send the user to this command, so a misleading answer here is a dead
end at the end of three trails.

## The narrow, provable defect: the recommendation was sometimes a constant

`analyze` returns `max(_MIN_THRESHOLD, mean * _HEADROOM)` — 0.002 and 0.5. So:

    is_silent fires when   mean < 0.002
    the clamp binds when   mean < 0.004

Between them sits a band where `is_silent` is False, so nothing warns, **and** the clamp has
bound, so the printed "recommended" is the floor and carries nothing from the sample. Laptop
room noise lands in it. The first run above, 0.0036, is exactly there.

That is now reported, and `--set` refuses: writing a gate below the room level that produced
it costs silent nonsense, while refusing costs a re-run.

## The wider problem, which is not fixable by a threshold

`mic-level` cannot tell speech from room tone, and the obvious discriminator does not work.
Measured across a real 1619-event corpus:

    clips WITH text     n=1114   peak/mean  p10  8.5   median 11.9   p90 17.3
    clips with NO text  n=  60   peak/mean  p10  6.7   median  8.6   p90 21.8

The distributions overlap, and the no-text p90 is *above* the speech p90. No cutoff
separates them. This is recorded so nobody spends an afternoon rediscovering it — the same
role `test_phonetic_needs_a_known_wordlist.py` plays for edit distance.

So the assumption is stated rather than hidden, for every reading and not just the clamped
band: the judgement goes to the person who knows whether they were speaking.

## Not done here

A real fix measures twice — ambient, then speech — and puts the gate between them. The
product already records ambient in `yazses doctor --mic` and never combines the two. That
changes an interactive flow and the meaning of `--set`, so it is written up rather than
slipped in.
"""

from __future__ import annotations

import numpy as np
import pytest

from yazses.system.miclevel import _HEADROOM, _MIN_THRESHOLD, analyze


def _sample(mean: float, n: int = 16000) -> np.ndarray:
    return np.full(n, mean, dtype=np.float32)


def test_the_gap_between_the_two_guards_exists() -> None:
    """The premise, stated as arithmetic so a change to either constant fails here."""
    assert _MIN_THRESHOLD / _HEADROOM > _MIN_THRESHOLD, (
        "the clamp and the silence check now coincide — re-read this file, the band it "
        "describes has closed"
    )


@pytest.mark.parametrize("mean", [0.0021, 0.0036, 0.0039])
def test_a_room_noise_sample_is_reported_as_uncalibratable(mean: float) -> None:
    """The band: not silent, but the number is the floor rather than a measurement."""
    stats = analyze(_sample(mean), 16000)
    assert stats.is_silent is False, "this sample is above the silence floor by design"
    assert stats.clamped is True
    assert stats.recommended_threshold == _MIN_THRESHOLD


@pytest.mark.parametrize("mean", [0.0041, 0.01, 0.05])
def test_a_real_speech_level_is_not_flagged(mean: float) -> None:
    """The opposite failure: flagging every sample would make the command useless."""
    stats = analyze(_sample(mean), 16000)
    assert stats.clamped is False
    assert stats.recommended_threshold == pytest.approx(mean * _HEADROOM, abs=1e-4)


def test_silence_still_reports_silence() -> None:
    stats = analyze(_sample(0.0005), 16000)
    assert stats.is_silent is True


def test_an_empty_recording_is_both() -> None:
    """Nothing captured cannot be calibrated from either."""
    stats = analyze(np.zeros(0, dtype=np.float32), 16000)
    assert stats.is_silent is True
    assert stats.clamped is True


def test_the_cli_refuses_to_write_a_floor_only_value() -> None:
    """`--set` wrote it. On this machine that is a gate below the room noise."""
    import inspect

    from yazses.cli import _calibrate_mic

    source = inspect.getsource(_calibrate_mic)
    # The CALL, not the name: `update_threshold_in_config` is also in the function's
    # import block, above everything, so a bare `index` compares against that and can
    # never fail. This is the third time today the same anchor mistake produced a
    # test that could not go red — see test_meeting_notes_reason.py.
    guard = source.index("if stats.clamped:")
    write = source.index("update_threshold_in_config(platform")
    assert guard < write, "the clamp check must run before --set writes anything"
    assert "too quiet to calibrate" in source


def test_the_cli_states_the_assumption_for_every_reading() -> None:
    """The clamp guard only covers a narrow band; the assumption holds for all of them.

    Four real runs of an empty room measured 0.0036 to 0.0050 — only the first fell in
    the band, and all four produced a recommendation below their own room noise.
    """
    import inspect

    from yazses.cli import _calibrate_mic

    source = inspect.getsource(_calibrate_mic)
    assert "was you speaking" in source
    assert "quiet room" in source


#: Peak-to-mean percentiles measured on this project's own 1619-event learning corpus.
#: The populations overlap and the no-text p90 is ABOVE the speech p90, so no cutoff
#: separates them.
PEAK_MEAN_SPEECH = (8.5, 11.9, 17.3)     # p10, median, p90 over 1114 clips WITH text
PEAK_MEAN_NO_TEXT = (6.7, 8.6, 21.8)     # p10, median, p90 over 60 clips with NO text


def test_the_measured_populations_overlap() -> None:
    """The negative result, stated as the arithmetic that makes a cutoff impossible.

    Any cutoff `c` must be above the speech p10 to admit speech and below the no-text
    p90 to reject noise; both are true across most of the range, which is what "no
    cutoff works" means.
    """
    s_p10, _s_med, s_p90 = PEAK_MEAN_SPEECH
    n_p10, _n_med, n_p90 = PEAK_MEAN_NO_TEXT
    assert n_p10 < s_p10, "noise reaches below the tenth percentile of speech"
    assert n_p90 > s_p90, "noise reaches above the ninetieth percentile of speech"


def test_no_peak_to_mean_cutoff_has_been_added() -> None:
    """The guard that earns its place: it fails if someone adds the disproved fix.

    Rediscovering that this does not work costs an afternoon. `analyze` uses peak only
    for reporting, never to decide anything.
    """
    import ast
    import inspect

    from yazses.system import miclevel

    fn = ast.parse(inspect.getsource(miclevel.analyze)).body[0]
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body
    code = "\n".join(ast.unparse(node) for node in body)
    assert "peak /" not in code and "peak/" not in code, (
        "a peak-to-mean ratio is being used to decide something — measured on 1174 real "
        "clips the speech and no-text populations overlap, so it cannot separate them"
    )
