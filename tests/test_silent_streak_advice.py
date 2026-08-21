"""Following the product's own advice for a silent-clip streak reached a dead end.

Found on the live daemon, not by reading. `yazses status` reported:

    ⚠ mic:    2 silent clips in a row — run `yazses audio status`

and `yazses audio status` answered:

    ⚠ silent clips in a row: 2 — mic may have changed.

That is a diagnosis with **no remedy**. The one surface that named a command was the
desktop toast, which fires once, at `silent_streak_threshold` (default 3) — a streak the
CLI displays from 1. So the user is sent to a screen that tells them something is wrong,
guesses why, and stops.

Three surfaces, three phrasings, one fault. This repo has hit that shape before and fixed
it the same way (`recimport.factory.diarization_advice`, shared by the daemon and the
meeting CLI so they cannot drift).

## The cause was asserted, not known

A silent discard is by definition `mean(|audio|) < vad_threshold`. That has exactly three
causes: nothing was said, the gate is above this voice, or capture is not receiving this
microphone. *"Your mic may have changed"* is only the third — and on a typical Linux
desktop it is the one YazSes can least confirm, because the OS default is a routing alias
whose name does not change when the device behind it does.

`yazses audio status` printed that very warning two lines above the guess:

    ⚠ that is a routing alias, not a microphone — the device behind it
      can change without this name changing
    ...
    ⚠ silent clips in a row: 2 — mic may have changed.

All three causes are named now, in the order a user can act on them.

## Deliberately not fixed here

The `status` → `audio status` hop itself. Sending a user one command deeper is reasonable
once the destination actually helps, and collapsing it would put four lines of advice into
a summary that is meant to be scannable.
"""

from __future__ import annotations

import pytest

from yazses.audio.device_monitor import silent_streak_advice


def test_the_plain_case_names_a_command_to_run() -> None:
    """The defect: a diagnosis with nothing to do about it."""
    headline, remedies = silent_streak_advice(3)
    assert remedies, "a streak was reported with no remedy at all"
    joined = " ".join(remedies)
    assert "yazses mic-level" in joined
    assert "yazses audio" in joined
    assert "3" in headline


@pytest.mark.parametrize(
    "cause",
    ["nothing was said", "gate is above your voice", "capture is not getting this mic"],
)
def test_all_three_causes_are_named(cause: str) -> None:
    """A silent discard is `mean(|audio|) < threshold` — these are the only three.

    Naming one of them as *the* cause is a guess, and it was the guess the product could
    least confirm.
    """
    _headline, remedies = silent_streak_advice(2)
    assert cause in " ".join(remedies).lower()


def test_the_mic_change_guess_is_no_longer_stated_as_the_cause() -> None:
    """Pinned so it does not come back as the confident single explanation."""
    headline, remedies = silent_streak_advice(2)
    text = f"{headline} {' '.join(remedies)}".lower()
    assert "may have changed" not in text


def test_the_healed_case_says_what_was_done_and_how_to_undo_it() -> None:
    """Auto-heal already switched the device; advice to go hunting would be wrong."""
    headline, remedies = silent_streak_advice(
        4, active="default", last_good="Blue Yeti", healed=True
    )
    joined = " ".join(remedies)
    assert "Blue Yeti" in joined
    assert "yazses audio use" in joined
    assert "default" in headline
    assert "mic-level" not in joined, (
        "the device was just switched — measuring the gate is not the next step"
    )


def test_healed_without_a_last_good_device_falls_back_to_the_full_advice() -> None:
    """`last_good` is `(none yet)` on a fresh install, which is exactly when a streak
    is most likely — a headline claiming a switch that did not happen would be false."""
    _headline, remedies = silent_streak_advice(3, healed=True, last_good=None)
    assert "mic-level" in " ".join(remedies)


def test_it_is_pure_and_reachable_from_both_surfaces() -> None:
    """The point of extracting it: the toast and the CLI cannot drift apart again."""
    import inspect

    from yazses.cli import audio_status
    from yazses.core import daemon

    assert "silent_streak_advice" in inspect.getsource(audio_status)
    assert "silent_streak_advice" in inspect.getsource(daemon.Daemon._note_silent_discard)


def test_a_streak_of_one_still_produces_usable_advice() -> None:
    """The CLI shows the streak from 1; the toast waits for the threshold."""
    headline, remedies = silent_streak_advice(1)
    assert "1" in headline
    assert remedies
