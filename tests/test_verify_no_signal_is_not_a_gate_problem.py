"""`yazses verify` told a silent room to lower a gate that cannot go that low.

Run for real on this machine, nobody speaking:

    [OK]   Capture: recorded audio from the input device
    [FAIL] Signal: level 0.0007 is below the silence gate 0.0020, so real speech
           would be discarded. Fix with `yazses mic-level --set`.

Two things are wrong with that line, and the second one makes it a loop.

**It asserts what it did not observe.** "Real speech would be discarded" is a claim about
speech, from a run in which no speech was heard. This module already refuses to make the
mirror-image claim — `test_verify_silence_verdict.py` exists because it once certified a
microphone that was hearing nobody, and the fix was to stop concluding more than the run
proved. The same reasoning was never applied to the failing side.

**And the fix it prescribes cannot do the thing it is prescribed for.**
`system/miclevel.py` will never recommend a threshold below `_MIN_THRESHOLD = 0.002` —
deliberately, so a silent room cannot calibrate the gate down onto its own noise floor.
So at level 0.0007 the user runs `yazses mic-level --set`, the gate stays at 0.002,
`verify` fails identically, and nothing in either output says why. The setter was
careful; the recommender was not.

The split is measured rather than guessed, in the shape `_CLEAR_MARGIN` already uses.
From 1646 real bursts in a live corpus:

    at or below 0.0005      37 events, **0 of which ever produced text**
                            (39 of the 41 bursts the daemon marked `silent` live here,
                             median level 0.00001 — a muted mic or the wrong device)
    quietest burst that
    produced text           0.0050 — ten times the floor

Nothing observed falls between. So below the floor the honest report is "no signal, and
here is what that means"; above it and below the gate, "quiet speech" is a real
possibility and the old advice is right — with the hedge that this step cannot tell it
from no speech at all.
"""
from __future__ import annotations

from yazses.system.miclevel import _MIN_THRESHOLD
from yazses.system.verify import _NO_SIGNAL_FLOOR, verify


def _ok(**over):
    kwargs = dict(
        record=lambda: object(),
        level_of=lambda a: 0.05,
        threshold=0.002,
        transcribe=lambda a: "hello world",
    )
    kwargs.update(over)
    return kwargs


def test_a_level_below_the_floor_is_not_reported_as_a_gate_problem() -> None:
    """The run that started this: 0.0007 against a 0.0020 gate."""
    result = verify(**_ok(level_of=lambda a: 0.0007, threshold=0.0220))

    assert not result.ok
    assert result.failure is not None
    assert result.failure.name == "Signal"
    detail = result.failure.detail
    assert "no signal" in detail
    assert "mic-level --set" not in detail, (
        "the prescribed command cannot produce a gate this low — see _MIN_THRESHOLD"
    )
    assert "audio devices" in detail, "name the check the user can actually run"
    assert "run this again and speak" in detail


def test_the_no_signal_message_does_not_claim_speech_was_discarded() -> None:
    """It heard no speech; it must not report on speech."""
    detail = verify(**_ok(level_of=lambda a: 0.0001, threshold=0.0220)).failure.detail
    assert "real speech" not in detail
    assert "would be discarded" not in detail


def test_quiet_speech_below_the_gate_still_gets_the_fix_and_now_a_hedge() -> None:
    """Above the floor, "your gate is too high" is a live possibility — keep the fix."""
    result = verify(**_ok(level_of=lambda a: 0.0230, threshold=0.0240))

    assert not result.ok
    detail = result.failure.detail
    assert "mic-level --set" in detail
    assert "cannot tell quiet speech from no speech" in detail, (
        "the one thing this step genuinely cannot decide has to be said out loud"
    )


def test_pure_silence_keeps_its_own_more_specific_message() -> None:
    detail = verify(**_ok(level_of=lambda a: 0.0)).failure.detail
    assert "muted, dead" in detail


def test_the_floor_sits_below_every_level_that_ever_produced_text() -> None:
    """Guard the constant, not just the branch.

    The quietest burst in the measured corpus that produced any text at all was
    0.0050. A floor anywhere near it would start calling real speech "no signal",
    which is the failure this branch exists to avoid making in the other direction.
    """
    quietest_speaking_burst = 0.0050
    assert 0 < _NO_SIGNAL_FLOOR <= quietest_speaking_burst / 2


def test_the_floor_is_below_anything_mic_level_could_ever_recommend() -> None:
    """This is what makes the old advice a loop rather than merely imprecise.

    If the floor were above `_MIN_THRESHOLD`, a level under it could still be fixed by
    lowering the gate, and refusing to say so would be the new bug.
    """
    assert _NO_SIGNAL_FLOOR == _MIN_THRESHOLD, (
        "the recommender and the setter must agree, or `mic-level --set` is recommended "
        "for a level it can never reach"
    )


def test_the_three_signal_branches_are_all_reachable() -> None:
    """A guard that iterates is green on an empty collection; so is a dead branch."""
    seen = {
        verify(**_ok(level_of=lambda a: lvl, threshold=0.0220)).failure.detail[:40]
        for lvl in (0.0, _NO_SIGNAL_FLOOR / 2, _NO_SIGNAL_FLOOR * 2)
    }
    assert len(seen) == 3, f"branches collapsed onto each other: {seen}"
