"""Click + gaze capture against the shapes a real desktop and a real camera produce (#397).

`tests/test_gaze_click_capture.py` pins the pairing rules with tidy numeric streams. A fake
click stream is tidy in ways a real input stack is not, and each test here models one way
reality differs -- the kind of difference a fake hid in this programme's earlier defects:

* **Two clocks.** The gaze samples are stamped by the shared source with ``time.monotonic``;
  an input stack hands out its own timestamps, and a wall-clock one is ~1.7e9 against a
  monotonic clock that counts from boot. Paired as-is, every click is "stale" -- which sends
  the user to a camera that is fine. It must be named for what it is, once, in words.
* **A burst of clicks.** A double-click, a click-spam or an auto-clicker lands several clicks
  inside one camera frame. One eye observation is one piece of evidence; counting it per
  click over-weights it and puts a copy in the held-out set that was trained on.
* **A poller that lags.** The ring is fed on its own cadence; at the instant of a click it
  can be a whole poll interval behind a source that already holds the right sample.
* **A camera that dies after it opened.** The service stays ``running``, every click is
  ``no_gaze``, and nothing says why unless the source's reason is asked for.
* **Order.** Clicks delivered out of timestamp order, gaze that arrives after the click.

The numbers are synthetic stream parameters that exercise boundaries; none is a claim about
a person's eyes or about any platform's input latency. Hermetic: a fake clock, a fake
observer, and the real ``SharedPerceptionSource`` over a fake capture and processor.
"""
from __future__ import annotations

import logging
import threading
import time
import types

import pytest

from tests.test_gaze_click_capture import FakeLease, FakeObserver, gaze
from yazses.gaze.association import DEFAULT_CAPACITY, RejectReason
from yazses.gaze.capture import (
    MAX_CLICK_CLOCK_SKEW_S,
    CaptureStats,
    ClickGazeCapture,
    ImplicitCaptureService,
)
from yazses.gaze.clicks import ClickEvent
from yazses.perception import SharedPerceptionSource, SourceState
from yazses.perception.signals import GazeSignal, PerceptionSample


class Clock:
    def __init__(self, now: float = 5000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def capture_with(clock: Clock | None = None):
    got: list = []
    return got, ClickGazeCapture(got.append, clock=clock)


# --------------------------------------------------------------------------- #
# Two clocks
# --------------------------------------------------------------------------- #


def test_a_wall_clock_click_is_a_clock_mismatch_not_a_stale_face(caplog) -> None:
    clock = Clock(5000.0)
    got, cap = capture_with(clock)
    cap.record_gaze(gaze(4999.9))
    wall_clock = 1_760_000_000.0  # an input stack's time.time(), against a boot-based clock
    with caplog.at_level(logging.WARNING, logger="yazses.gaze.capture"):
        result = cap.handle_click(ClickEvent(wall_clock, 123456.789, 654321.5))
    assert result.reason is RejectReason.CLOCK_MISMATCH
    stats = cap.stats()
    assert (stats.clock_mismatch, stats.stale, stats.accepted, stats.rejected) == (1, 0, 0, 1)
    assert got == []
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "monotonic" in text
    assert "123456" not in text and "654321" not in text, "a click position reached a log line"


def test_the_clock_mismatch_is_explained_once_not_per_click(caplog) -> None:
    clock = Clock(5000.0)
    _, cap = capture_with(clock)
    with caplog.at_level(logging.WARNING, logger="yazses.gaze.capture"):
        for _ in range(50):
            cap.handle_click(ClickEvent(1_760_000_000.0, 1.0, 1.0))
    assert len([r for r in caplog.records if "monotonic" in r.getMessage()]) == 1
    assert cap.stats().clock_mismatch == 50


def test_a_boot_time_clock_that_includes_suspend_is_also_named() -> None:
    """The other direction: a clock that kept counting while the laptop slept is hours ahead."""
    clock = Clock(5000.0)
    _, cap = capture_with(clock)
    cap.record_gaze(gaze(4999.9))
    assert cap.handle_click(ClickEvent(5000.0 + 7200.0, 1.0, 1.0)).reason is (
        RejectReason.CLOCK_MISMATCH
    )
    assert cap.handle_click(ClickEvent(5000.0 - 7200.0, 1.0, 1.0)).reason is (
        RejectReason.CLOCK_MISMATCH
    )


def test_a_click_a_little_off_the_clock_is_still_a_click() -> None:
    """Delivery jitter must not look like a different clock (the guard fires rarely)."""
    clock = Clock(5000.0)
    got, cap = capture_with(clock)
    cap.record_gaze(gaze(4999.9))
    inside = MAX_CLICK_CLOCK_SKEW_S - 1.0
    assert cap.handle_click(ClickEvent(5000.0 + inside, 1.0, 1.0)).reason is not (
        RejectReason.CLOCK_MISMATCH
    )
    assert cap.handle_click(ClickEvent(5000.0, 1.0, 1.0)).accepted
    assert len(got) == 1


def test_without_a_clock_the_check_is_off_and_old_behaviour_is_unchanged() -> None:
    _, cap = capture_with(None)
    cap.record_gaze(gaze(4999.9))
    assert cap.handle_click(ClickEvent(1_760_000_000.0, 1.0, 1.0)).reason is RejectReason.STALE
    assert cap.stats().clock_mismatch == 0


# --------------------------------------------------------------------------- #
# A burst of clicks draws on one observation once
# --------------------------------------------------------------------------- #


def test_a_double_click_inside_one_camera_frame_is_one_observation() -> None:
    got, cap = capture_with()
    cap.record_gaze(gaze(99.9))
    first = cap.handle_click(ClickEvent(100.00, 10.0, 10.0))
    second = cap.handle_click(ClickEvent(100.04, 10.0, 10.0))
    assert first.accepted and second.reason is RejectReason.SAMPLE_REUSED
    assert len(got) == 1
    stats = cap.stats()
    assert (stats.clicks, stats.accepted, stats.sample_reused, stats.rejected) == (2, 1, 1, 1)


def test_a_thousand_clicks_in_one_frame_reach_the_estimator_once() -> None:
    got, cap = capture_with()
    cap.record_gaze(gaze(99.9))
    for i in range(1000):
        cap.handle_click(ClickEvent(100.0 + i * 1e-5, 10.0, 10.0))
    assert len(got) == 1
    assert cap.stats() == CaptureStats(clicks=1000, accepted=1, sample_reused=999)


def test_the_next_frame_is_new_evidence() -> None:
    got, cap = capture_with()
    cap.record_gaze(gaze(99.90))
    cap.handle_click(ClickEvent(100.0, 10.0, 10.0))
    cap.record_gaze(gaze(100.05))
    assert cap.handle_click(ClickEvent(100.15, 20.0, 20.0)).accepted
    assert [p.gaze_timestamp_s for p in got] == [99.90, 100.05]


def test_a_click_that_was_rejected_does_not_use_the_sample_up() -> None:
    clock = Clock(100.0)
    got, cap = capture_with(clock)
    cap.record_gaze(gaze(99.9))
    assert cap.handle_click(ClickEvent(1_760_000_000.0, 1.0, 1.0)).reason is (
        RejectReason.CLOCK_MISMATCH
    )
    assert cap.handle_click(ClickEvent(100.0, 1.0, 1.0)).accepted
    assert len(got) == 1


def test_a_reused_sample_is_never_swapped_for_another_one() -> None:
    """Reject, never repair: the second click does not get the next-best observation."""
    got, cap = capture_with()
    cap.record_gaze(gaze(99.80, x=0.1))
    cap.record_gaze(gaze(99.90, x=0.2))
    assert cap.handle_click(ClickEvent(100.0, 1.0, 1.0)).accepted          # takes 99.90
    again = cap.handle_click(ClickEvent(100.0, 1.0, 1.0))
    assert again.reason is RejectReason.SAMPLE_REUSED
    assert [p.gaze for p in got] == [(0.2, 0.2)]


def test_the_memory_of_used_samples_is_bounded() -> None:
    _, cap = capture_with()
    for i in range(DEFAULT_CAPACITY * 5):
        cap.record_gaze(gaze(10.0 + i * 0.1))
        cap.handle_click(ClickEvent(10.0 + i * 0.1 + 0.1, 1.0, 1.0))
    assert len(cap._used) <= DEFAULT_CAPACITY
    assert cap.stats().accepted == DEFAULT_CAPACITY * 5


def test_two_threads_clicking_at_once_cannot_both_win_one_sample() -> None:
    got, cap = capture_with()
    cap.record_gaze(gaze(99.9))
    barrier = threading.Barrier(8)

    def click() -> None:
        barrier.wait()
        for _ in range(200):
            cap.handle_click(ClickEvent(100.0, 1.0, 1.0))

    threads = [threading.Thread(target=click) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(got) == 1
    assert cap.stats().clicks == 1600


# --------------------------------------------------------------------------- #
# Order and direction of time
# --------------------------------------------------------------------------- #


def test_gaze_stamped_after_the_click_is_never_its_evidence() -> None:
    got, cap = capture_with()
    cap.record_gaze(gaze(100.05))     # the eyes moved on to somewhere else after the click
    assert cap.handle_click(ClickEvent(100.0, 1.0, 1.0)).reason is RejectReason.STALE
    assert got == []


def test_clicks_delivered_out_of_timestamp_order_pair_with_their_own_moment() -> None:
    got, cap = capture_with()
    for t, x in ((99.0, 0.1), (100.0, 0.2), (101.0, 0.3)):
        cap.record_gaze(gaze(t, x=x))
    cap.handle_click(ClickEvent(101.1, 1.0, 1.0))
    cap.handle_click(ClickEvent(100.1, 2.0, 2.0))     # delivered late, stamped earlier
    assert [(p.gaze[0], p.click[0]) for p in got] == [(0.3, 1.0), (0.2, 2.0)]


def test_the_ring_ignores_a_gaze_sample_that_goes_back_in_time() -> None:
    _, cap = capture_with()
    assert cap.record_gaze(gaze(100.0))
    assert not cap.record_gaze(gaze(99.0))
    assert len(cap.history) == 1


# --------------------------------------------------------------------------- #
# The poller lags the source
# --------------------------------------------------------------------------- #


def service(clock: Clock | None = None, **kwargs):
    observer, lease = FakeObserver(), FakeLease()
    got: list = []
    cap = ClickGazeCapture(got.append, clock=clock)
    svc = ImplicitCaptureService(capture=cap, observer=observer, lease=lease, **kwargs)
    return svc, observer, lease, cap, got


def test_a_click_reads_the_source_itself_instead_of_trusting_the_last_poll() -> None:
    """At 1 fps the poll interval is longer than the look-back window: without a read on
    the click, a fresh sample sitting in the source would make the click 'no gaze'."""
    svc, observer, lease, cap, got = service(interval_s=60.0)
    svc.start()
    lease.sample = PerceptionSample(99.9, gaze=GazeSignal(99.9, 0.1, 0.2, 0.9))
    assert len(cap.history) == 0, "nothing has polled yet"
    observer.click(100.0, 5.0, 6.0)
    assert len(got) == 1 and got[0].click == (5.0, 6.0)
    svc.stop()


def test_a_source_that_raises_on_read_cannot_take_the_click_hook_down() -> None:
    svc, observer, lease, cap, _ = service()

    def boom():
        raise RuntimeError("source exploded")

    lease.latest = boom  # type: ignore[method-assign]
    svc.start()
    observer.click(100.0, 1.0, 1.0)                    # must not raise
    assert cap.stats().clicks == 1
    svc.stop()


# --------------------------------------------------------------------------- #
# A camera that dies after it opened
# --------------------------------------------------------------------------- #


class _Capture:
    def __init__(self) -> None:
        self.dead = False
        self.closed = False

    def open(self) -> None:
        pass

    def read(self):
        if self.dead:
            raise OSError("device disconnected")
        return object()

    def close(self) -> None:
        self.closed = True


class _Processor:
    name = "fake"

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def process(self, frame, timestamp_s):
        return PerceptionSample(timestamp_s, gaze=GazeSignal(timestamp_s, 0.1, 0.2, 0.9))

    def close(self) -> None:
        pass


class _NoThread:
    def join(self, timeout=None) -> None:
        pass

    def is_alive(self) -> bool:
        return False


def real_source(clock: Clock):
    capture = _Capture()
    source = SharedPerceptionSource(
        lambda: capture,
        lambda: _Processor(clock),
        clock=clock,
        spawn=lambda body, name: _NoThread(),
    )
    return source, capture


def test_a_camera_that_dies_after_opening_is_explained_once_while_clicks_keep_arriving(
    caplog,
) -> None:
    clock = Clock(5000.0)
    source, capture = real_source(clock)
    observer = FakeObserver()
    cap = ClickGazeCapture(lambda pair: None, clock=clock)
    svc = ImplicitCaptureService(
        capture=cap,
        observer=observer,
        lease=source.consumer("gaze-refine"),
        failure_reason=lambda: source.status().failure_reason,
    )
    svc.start()
    assert source.observe() and svc.poll()
    clock.now += 0.1
    observer.click(clock.now, 1.0, 1.0)
    assert cap.stats().accepted == 1

    capture.dead = True
    with caplog.at_level(logging.WARNING, logger="yazses.gaze.capture"):
        assert not source.observe()
        assert source.status().state is SourceState.FAILED
        clock.now += 5.0
        for _ in range(5):
            observer.click(clock.now, 1.0, 1.0)
            clock.now += 0.1
    assert svc.running, "the service cannot know; only the reason tells the user"
    assert cap.stats().no_gaze + cap.stats().stale == 5
    reasons = [
        r for r in caplog.records
        if r.name == "yazses.gaze.capture" and "device disconnected" in r.getMessage()
    ]
    assert len(reasons) == 1, "the dead camera must be named exactly once, by this service"
    svc.stop()


def test_the_same_source_and_clock_pair_a_click_with_the_gaze_before_it() -> None:
    """The positive control for the failure tests: one clock, one live source, one pair."""
    clock = Clock(5000.0)
    source, _ = real_source(clock)
    got: list = []
    cap = ClickGazeCapture(got.append, clock=clock)
    observer = FakeObserver()
    svc = ImplicitCaptureService(capture=cap, observer=observer, lease=source.consumer("g"))
    svc.start()
    source.observe()
    clock.now += 0.1
    observer.click(clock.now, 7.0, 8.0)
    assert len(got) == 1 and got[0].lag_s == pytest.approx(0.1)
    svc.stop()
    assert source.status().state is SourceState.DORMANT


# --------------------------------------------------------------------------- #
# Wiring: the daemon's runtime knows the clock and the failure reason
# --------------------------------------------------------------------------- #


def test_the_runtime_builder_hands_the_clock_and_the_failure_reason_to_the_capture(
    tmp_path,
) -> None:
    from tests.test_gaze_refine_runtime import build

    class Perception:
        def __init__(self) -> None:
            from tests.test_gaze_refine_runtime import FakeLease as Lease

            self.lease = Lease()

        def consumer(self, name):
            return self.lease

        def status(self):
            return types.SimpleNamespace(failure_reason="the camera could not be opened")

    runtime, reason, _, _, _ = build(tmp_path, perception=Perception(), clock=Clock(5000.0))
    assert runtime is not None, reason
    runtime.capture.record_gaze(gaze(4999.9))
    assert runtime.capture.handle_click(ClickEvent(1_760_000_000.0, 1.0, 1.0)).reason is (
        RejectReason.CLOCK_MISMATCH
    )
    assert runtime.service._failure_reason is not None
    runtime.stop()


def test_the_daemon_builds_its_capture_on_the_monotonic_clock_the_source_uses() -> None:
    from tests.test_gaze_refine_wiring import FakeObserver as WiringObserver
    from tests.test_gaze_refine_wiring import _daemon

    daemon = _daemon(observer=WiringObserver())
    runtime = daemon._build_gaze_refinement(daemon._config)
    assert runtime is not None
    try:
        now = time.monotonic()
        runtime.capture.record_gaze(gaze(now - 0.1))
        assert runtime.capture.handle_click(ClickEvent(now, 1.0, 1.0)).accepted
        wall = runtime.capture.handle_click(ClickEvent(time.time(), 1.0, 1.0))
        assert wall.reason is RejectReason.CLOCK_MISMATCH
    finally:
        runtime.stop()
