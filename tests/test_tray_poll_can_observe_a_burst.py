"""The tray's idle poll has to be quicker than a hold-to-talk burst is short.

Reported first-hand from Windows, 2026-08-27: dictation worked and produced correct
text, and *"the color of the icon does not change"*. The colour policy was not at
fault -- `icon_spec` maps `recording` to green and `tray/menu.py` is unit-tested --
the tray simply never looked while it was true.

The tray drives its icon by polling the daemon's `status` RPC. It polled every
**1.0 s** at rest and only dropped to 0.15 s *after* it had already observed a
recording state, which is a chicken-and-egg: the fast rate exists to track a burst
that the slow rate has to catch first. A burst that starts just after one sample and
ends before the next is never observed at all, and one that is caught shows colour
for a fraction of its length. At a typical 1-2 s hold that reads exactly as "the icon
does not change".

The overlay -- the other status-polling process, watching the same transition --
already had this right at 0.25 s, with the comment *"quick enough to catch recording
start"*. The reasoning was written down in one of the two processes that needed it.

These are floors on sampling, not cosmetics, so they are asserted as inequalities
against the burst length rather than pinned to literals: raising the rate later must
stay legal, lowering it past the point where a burst can be missed must not.
"""

from __future__ import annotations

from yazses.overlay.poller import _SLOW_INTERVAL_S
from yazses.tray.app import _FAST_POLL_INTERVAL_S, _POLL_INTERVAL_S

#: A deliberately short hold-to-talk burst. Real dictation runs longer; this is the
#: shortest utterance the icon should still visibly track.
_SHORT_BURST_S = 1.0

#: Nyquist, applied to a state transition: to *see* a state you must sample inside
#: it, and to see it reliably you need at least two samples in its lifetime.
_MIN_SAMPLES_IN_A_BURST = 2


def test_the_idle_poll_samples_a_short_burst_more_than_once() -> None:
    """The actual bug: at 1.0 s a 1 s burst could be missed entirely."""
    samples = _SHORT_BURST_S / _POLL_INTERVAL_S
    assert samples >= _MIN_SAMPLES_IN_A_BURST, (
        f"the tray polls every {_POLL_INTERVAL_S}s at rest, so a {_SHORT_BURST_S}s "
        f"hold is sampled about {samples:.1f} times. The icon cannot show a state it "
        f"never observes -- this is what 'the colour never changes' looks like."
    )


def test_the_idle_poll_is_not_slower_than_the_overlay_watching_the_same_transition() -> None:
    """Two processes, one transition. The slower one is the one that misses it.

    Not a style rule: the overlay's 0.25 s carries the reasoning ("quick enough to
    catch recording start") for a decision the tray was making independently and
    getting wrong.
    """
    assert _POLL_INTERVAL_S <= _SLOW_INTERVAL_S, (
        f"the tray polls every {_POLL_INTERVAL_S}s but the overlay polls every "
        f"{_SLOW_INTERVAL_S}s to catch the same recording start."
    )


def test_the_recording_poll_is_still_the_faster_of_the_two() -> None:
    """Anti-vacuity: the two rates must stay ordered, or the fast one is pointless."""
    assert _FAST_POLL_INTERVAL_S < _POLL_INTERVAL_S


def test_neither_rate_is_a_busy_loop() -> None:
    """A floor as well as a ceiling -- this runs against a named pipe on Windows."""
    assert _FAST_POLL_INTERVAL_S >= 0.05
    assert _POLL_INTERVAL_S >= 0.1
