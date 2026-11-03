"""Pinned timing of ``yazses.biosignal.runner`` (companion to test_biosignal_runner.py).

Two soft spots are measured here, not fixed. Both tests drive ``step()`` with a fake clock
and synthetic blocks: no sleeping, no hardware, no randomness beyond a seeded generator.

1. **Dead time after a backlog discard.** A slow callback makes the runner drop what the
   device queued and reset the pipeline. The quality monitor then starts in its warm-up
   state, so detections are suppressed until it has filled ``min_fill_s`` of signal and
   seen ``recover_windows`` clean evaluations ``hop_s`` apart. The test pins the measured
   dead time per block size and checks it against that formula.

2. **A blink in the same block as a release.** The runner handles a block's squeeze
   transitions before its intents, so a blink that preceded the release in time is
   dispatched after ``on_mode_end``. The test pins the lateness, in blocks and in seconds.
"""

from __future__ import annotations

import numpy as np
import pytest

from yazses.biosignal.pipeline import BiosignalPipeline, PipelineParts
from yazses.biosignal.quality import QualityThresholds, SignalQualityMonitor
from yazses.biosignal.runner import BiosignalRunner, RunnerCallbacks
from yazses.biosignal.types import BioEvent, ChannelInfo, EventKind, SampleBlock, SignalKind

FS = 100.0
CH = (ChannelInfo("emg0", SignalKind.EMG),)
ON, OFF, BLINK = EventKind.SQUEEZE_ON, EventKind.SQUEEZE_OFF, EventKind.DOUBLE_BLINK


class Src:
    """A finite list of blocks; ``read`` returns None when it is empty (live-like)."""

    fs = FS
    channels = CH

    def __init__(self, blocks=()):
        self.q = list(blocks)

    def start(self):
        pass

    def read(self):
        return self.q.pop(0) if self.q else None

    def stop(self):
        pass


class Det:
    """A detector whose output for the next block is pushed by the test."""

    def __init__(self):
        self.q: list[list[BioEvent]] = []

    def push(self, events):
        self.q.append(list(events))

    def process(self, block):
        return self.q.pop(0) if self.q else []

    def reset(self):
        pass


def _block(i: int, n: int, rng) -> SampleBlock:
    dt = n / FS
    return SampleBlock(data=rng.normal(0.0, 20.0, (1, n)), fs=FS, channels=CH,
                       t0=round(i * dt, 6))


def _ev(kind, t, **detail):
    return BioEvent(kind=kind, t=t, confidence=0.9, channel="emg0", detail=dict(detail))


# ---------------------------------------------------------------------------
# 1. Dead time after a discard


# Measured with the default QualityThresholds: the time from the first block after the
# discard to the end of the first block whose event is accepted. Keyed by block length in
# seconds. Each value is 2.75 s (min_fill_s + (recover_windows - 1) * hop_s) rounded up to
# the next block boundary, which is why 0.10 s blocks give 2.80 and the others 2.75.
DEAD_TIME_S = {0.01: 2.75, 0.05: 2.75, 0.10: 2.80, 0.25: 2.75}


def _dead_time(block_samples: int, *, discard: bool) -> tuple[int, float]:
    """Run a clean lead-in, a double blink whose callback is slow, then fresh signal.

    Returns (backlogs discarded, dead time in seconds). Dead time is None if no event was
    ever accepted.
    """
    n = block_samples
    dt = n / FS
    rng = np.random.default_rng(7)
    lead = round(4.0 / dt)           # 4 s of clean signal: the monitor is GOOD before the blink
    queued = 5                       # blocks the device sends during the slow callback
    t = [100.0]
    det = Det()
    starts: list[str] = []

    def on_intent(_intent):
        if discard:
            t[0] += 2.0              # the callback takes 2 s on the runner's clock

    src = Src([_block(i, n, rng) for i in range(lead + 1 + queued)])
    pipe = BiosignalPipeline(PipelineParts(detectors=[det], quality=SignalQualityMonitor()))
    runner = BiosignalRunner(
        lambda: src, lambda _s: pipe,
        RunnerCallbacks(on_mode_start=starts.append, on_intent=on_intent),
        watchdog_seconds=1.5, poll_seconds=0.001, clock=lambda: t[0], live=True)
    runner._source = src
    runner._pipeline = pipe

    for i in range(lead + 1):
        det.push([_ev(BLINK, i * dt)] if i == lead else [])
        assert runner.step() is True
        t[0] += dt
    # The blink's own step ran the slow callback, and that step discarded the queue.
    discarded = runner.status()["backlogs_discarded"]

    fresh = [_block(i, n, rng) for i in range(lead + 1 + queued, lead + 1 + queued + round(10 / dt))]
    src.q.extend(fresh)
    resume = fresh[0].t0
    for block in fresh:
        det.push([_ev(ON, block.t0, level="light")])
        runner.step()
        t[0] += dt
        if starts:
            return discarded, round(block.t0 + dt - resume, 6)
    return discarded, None


@pytest.mark.parametrize("block_samples", [1, 5, 10, 25])
def test_dead_time_after_a_discard_is_pinned_per_block_size(block_samples):
    dt = block_samples / FS
    discarded, dead = _dead_time(block_samples, discard=True)
    assert discarded == 1
    assert dead == pytest.approx(DEAD_TIME_S[round(dt, 2)], abs=1e-9)


@pytest.mark.parametrize("block_samples", [1, 5, 10, 25])
def test_dead_time_is_min_fill_plus_recovery_quantised_to_a_block(block_samples):
    """The pinned figure is the warm-up formula, not a tuned constant.

    The monitor judges first at ``min_fill_s``, then needs ``recover_windows - 1`` more
    evaluations ``hop_s`` apart to leave BAD. The block that carries the first accepted
    event can end up to one block after that.
    """
    thr = QualityThresholds()
    dt = block_samples / FS
    _, dead = _dead_time(block_samples, discard=True)
    floor = thr.min_fill_s + (thr.recover_windows - 1) * thr.hop_s
    assert floor == pytest.approx(2.75)
    assert floor - 1e-9 <= dead <= floor + dt + 1e-9


def test_control_without_a_discard_has_no_dead_time():
    """The same fixture with a quick callback: the monitor is already GOOD, so the first
    block after the blink is the first accepted one. The dead time is the block itself."""
    dt = 0.1
    discarded, dead = _dead_time(10, discard=False)
    assert discarded == 0
    assert dead == pytest.approx(dt, abs=1e-9)


# ---------------------------------------------------------------------------
# 2. A blink in the same block as a release


class Rig:
    """Blocks are fed one per step; callbacks append to ``log`` with the clock reading."""

    def __init__(self, *, release_seconds=0.0):
        self.t = [100.0]
        self.log: list[tuple[str, float, int]] = []
        self.step_no = 0
        self.cur = 0                     # index of the block being processed
        self.det = Det()
        self.release_seconds = release_seconds
        self.rng = np.random.default_rng(3)
        cbs = RunnerCallbacks(on_mode_start=self._start, on_mode_end=self._end,
                              on_intent=self._intent)
        self.src = Src()
        self.pipe = BiosignalPipeline(PipelineParts(detectors=[self.det]))
        self.runner = BiosignalRunner(
            lambda: self.src, lambda _s: self.pipe, cbs, watchdog_seconds=1.5,
            poll_seconds=0.001, clock=lambda: self.t[0], live=True)
        self.runner._source = self.src
        self.runner._pipeline = self.pipe

    def _start(self, mode):
        self.log.append((f"start:{mode}", self.t[0], self.cur))

    def _end(self):
        self.log.append(("end", self.t[0], self.cur))
        self.t[0] += self.release_seconds        # the seconds-long turn behind the release

    def _intent(self, intent):
        self.log.append((f"intent:{intent.label}", self.t[0], self.cur))

    def step(self, events):
        self.det.push(events)
        self.cur = self.step_no
        self.src.q.append(_block(self.step_no, 10, self.rng))
        self.step_no += 1
        self.runner.step()
        self.t[0] += 0.1


def test_blink_and_release_in_one_block_is_dispatched_after_the_release():
    """Same block, blink first in time: the callbacks run end -> intent, not in time order.

    Lateness in blocks is 0: the intent is delivered in the step that handled its own block.
    """
    rig = Rig()
    rig.step([_ev(ON, 0.0, level="light")])
    rig.step([_ev(BLINK, 0.2), _ev(OFF, 0.5)])
    labels = [name for name, _t, _s in rig.log]
    assert labels == ["start:full_text", "end", "intent:undo"]
    blink_block = 1
    intent_step = rig.log[-1][2]
    assert intent_step - blink_block == 0


def test_the_inversion_costs_the_release_duration_in_seconds_not_a_block():
    """With an 8 s release callback the intent arrives 8 s late, still in its own block."""
    rig = Rig(release_seconds=8.0)
    rig.step([_ev(ON, 0.0, level="light")])
    rig.step([_ev(BLINK, 0.2), _ev(OFF, 0.5)])
    (_, t_end, _), (_, t_intent, step_intent) = rig.log[1], rig.log[2]
    assert step_intent == 1                          # still the blink's own block
    assert t_intent - t_end == pytest.approx(8.0)    # the release callback's duration
    assert rig.log[2][1] - rig.log[0][1] == pytest.approx(8.1)


def test_blink_in_the_block_before_the_release_is_dispatched_at_once():
    """Control: blink and release in different blocks. The intent is 0 blocks and 0 s late
    even with an 8 s release callback, because the blink's own block carries no release."""
    rig = Rig(release_seconds=8.0)
    rig.step([_ev(ON, 0.0, level="light")])
    rig.step([_ev(BLINK, 0.2)])
    rig.step([_ev(OFF, 0.5)])
    labels = [(name, step) for name, _t, step in rig.log]
    assert labels == [("start:full_text", 0), ("intent:undo", 1), ("end", 2)]
