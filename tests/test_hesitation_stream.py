"""Hesitation-Hold Endpointing's producer (`yazses.hesitation.stream`) on synthetic signals.

numpy only — no optional backend, so no skip marker. The core rule (`hesitation.endpoint`) has
its own tests in `test_hesitation_contour.py`; these check that real frames reach it with the
right inputs. Signals come from `tests/synthetic_voice.py`; no recorded audio.
"""
from __future__ import annotations

import threading

import numpy as np

from tests.synthetic_voice import SR, glide, hum, silence, white_noise
from yazses.audio.pitch import track
from yazses.hesitation.endpoint import is_filled_pause
from yazses.hesitation.stream import (
    HesitationMonitor,
    filled_pause_inputs,
    trailing_filled_pause,
    trailing_window,
)


def _umm(seconds=0.6, hz=118.0):
    """A level, sustained nasal hum with a little room noise."""
    return hum(hz, seconds, noise=5e-4)


def _falling_phrase(seconds=0.6):
    """A speech-like declarative fall, 210 -> 120 Hz."""
    return hum(glide(210.0, 120.0, seconds), seconds, noise=5e-4)


def test_a_level_umm_is_a_filled_pause():
    frames = track(np.concatenate([_umm(), silence(0.3)]), SR)
    assert trailing_filled_pause(frames) is True
    f0, stability = filled_pause_inputs(frames)
    assert len(f0) == 40  # 400 ms tail at a 10 ms hop
    assert max(f0) - min(f0) < 5.0 and stability > 0.9


def test_a_falling_speech_like_contour_is_not():
    frames = track(np.concatenate([_falling_phrase(), silence(0.3)]), SR)
    assert trailing_filled_pause(frames) is False
    f0, _ = filled_pause_inputs(frames)
    voiced = [f for f in f0 if f > 0]
    assert max(voiced) - min(voiced) > 25.0  # the core's F0-range test is what rejects it


def test_a_short_flat_syllable_does_not_extend_the_endpoint():
    """150 ms of flat voicing is the end of an ordinary word, not a held hesitation."""
    syllable = hum(118.0, 0.15, noise=5e-4, ramp_s=0.03)
    frames = track(np.concatenate([silence(0.3), syllable, silence(0.3)]), SR)
    # Flat and steady, so the core alone *would* call it a filled pause: what keeps it out is
    # the sustained-voicing requirement this producer adds.
    f0, stability = filled_pause_inputs(frames)
    assert is_filled_pause(f0, stability) is True
    assert trailing_filled_pause(frames) is False
    assert trailing_filled_pause(frames, min_voiced_ms=100.0) is True


def test_the_window_ends_at_the_last_voiced_frame_through_trailing_noise():
    """Trailing room noise is unvoiced, so it neither hides nor imitates the hesitation."""
    frames = track(np.concatenate([_umm(), white_noise(0.5, level=2e-3)]), SR)
    window = trailing_window(frames)
    assert window and window[-1].voiced
    assert trailing_filled_pause(frames) is True


def test_noise_or_silence_alone_is_not_a_filled_pause():
    assert trailing_filled_pause(track(white_noise(1.0), SR)) is False
    assert trailing_filled_pause(track(silence(1.0), SR)) is False
    assert filled_pause_inputs(track(silence(1.0), SR)) == ([], 0.0)
    assert trailing_filled_pause([]) is False


def _feed(monitor, audio, chunk=512):
    for i in range(0, audio.size, chunk):
        monitor.push(audio[i:i + chunk])


def test_monitor_holds_after_an_umm_and_commits_after_speech():
    mon = HesitationMonitor(SR, commit_ms=800.0, hold_extra_ms=1200.0)
    _feed(mon, np.concatenate([_falling_phrase(), _umm(), silence(0.5)]))
    assert mon.last_was_filled_pause is True
    assert mon.decision(900.0) == "hold"     # past commit_ms, inside the extension
    assert mon.decision(2100.0) == "commit"  # past commit_ms + hold_extra_ms

    _feed(mon, np.concatenate([_falling_phrase(), silence(0.5)]))  # speech resumed, then ended
    assert mon.last_was_filled_pause is False
    assert mon.decision(900.0) == "commit"


def test_monitor_reset_forgets_the_previous_turn():
    mon = HesitationMonitor(SR)
    _feed(mon, _umm())
    assert mon.last_was_filled_pause is True
    mon.reset()
    assert mon.last_was_filled_pause is False
    mon.push(np.zeros(0, dtype=np.float32))  # an empty chunk is ignored
    assert mon.decision(900.0) == "commit"


def test_monitor_memory_stays_bounded_when_nobody_reads():
    """A plain hold-to-talk turn pushes but never asks; the queue must not grow unbounded."""
    mon = HesitationMonitor(SR, max_pending_s=1.0)
    _feed(mon, np.concatenate([_falling_phrase(3.0), _umm()]), chunk=1600)
    assert mon._pending_n <= SR * 1.0 + 1600
    assert mon.last_was_filled_pause is True  # the kept tail still holds the hesitation


def test_dropped_audio_clears_the_verdict_from_before_the_drop():
    """The dropped audio may hold newer speech, so a pre-drop umm must not keep holding."""
    stalled = HesitationMonitor(SR)  # max_pending_s = 2.0
    _feed(stalled, _umm())
    assert stalled.last_was_filled_pause is True
    # 3.5 s with no read: the falling speech is dropped, only trailing silence is kept.
    _feed(stalled, np.concatenate([_falling_phrase(1.0), silence(2.5)]))
    assert stalled.last_was_filled_pause is False
    assert stalled.decision(900.0) == "commit"

    # Without the stall, the speech is analysed and the verdict is False too.
    polled = HesitationMonitor(SR)
    _feed(polled, _umm())
    assert polled.last_was_filled_pause is True
    _feed(polled, np.concatenate([_falling_phrase(1.0), silence(0.5)]))
    assert polled.last_was_filled_pause is False


def test_push_does_not_wait_for_a_running_analysis():
    """The audio callback must never block on YIN: push takes only the queue lock."""
    mon = HesitationMonitor(SR)
    started, release = threading.Event(), threading.Event()
    real_feed = mon._tracker.feed

    def slow_feed(chunk):
        started.set()
        assert release.wait(5.0)
        return real_feed(chunk)

    mon._tracker.feed = slow_feed  # type: ignore[method-assign]
    mon.push(_umm())
    reader = threading.Thread(target=lambda: mon.last_was_filled_pause, daemon=True)
    reader.start()
    try:
        assert started.wait(5.0)  # the reader is now inside the analysis
        pusher = threading.Thread(target=mon.push, args=(silence(0.1),), daemon=True)
        pusher.start()
        pusher.join(2.0)
        assert not pusher.is_alive(), "push blocked behind the analysis"
    finally:
        release.set()
        reader.join(5.0)
    assert not reader.is_alive()
    mon._tracker.feed = real_feed  # type: ignore[method-assign]
    # The chunk pushed during the analysis was queued, not lost: the next read analyses it.
    assert mon._pending_n == silence(0.1).size
    assert mon.last_was_filled_pause is True  # 100 ms of silence keeps the umm verdict
    assert mon._pending_n == 0
