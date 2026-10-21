"""Click + gaze capture is bounded in age and dropped on a layout change (#397).

`tests/test_gaze_click_capture.py` pins the pairing rules and the count bound of the gaze
ring. Two properties of the samples were not yet pinned by anything:

* **Age.** The ring was bounded in count only, so when the face left the frame the last 64
  observations stayed in RAM until the service stopped. It is now also bounded in age
  (``DEFAULT_MAX_AGE_S``, never shorter than the look-back), and an emptied-by-age ring
  still says ``stale`` -- the face left -- rather than ``no_gaze``.
* **Topology.** A pair joins a click in the *current* layout's canonical coordinates with
  eye features from a moment ago. If the ADR-v2-149 context fingerprint (display layout +
  camera) changed in between, the ring is dropped and the click that noticed is refused as
  ``topology_changed``; only gaze recorded after the change can pair.

Hermetic: a fake clock, a fake click stream, fake gaze and a fake fingerprint. The numbers
are synthetic stream parameters, not claims about anyone's eyes or any platform.
"""
from __future__ import annotations

import dataclasses
import logging
import math

import pytest

from tests.test_gaze_click_capture import FakeLease, FakeObserver, gaze
from yazses.gaze.association import (
    DEFAULT_LOOKBACK_S,
    DEFAULT_MAX_AGE_S,
    AssociationPolicy,
    GazeHistory,
    RejectReason,
)
from yazses.gaze.capture import (
    CaptureStats,
    ClickGazeCapture,
    ImplicitCaptureService,
    ThrottledFingerprint,
)
from yazses.gaze.clicks import ClickEvent
from yazses.gaze.refine_runtime import context_fingerprint
from yazses.gaze.topology import CalibrationContext, Display, DisplayTopology
from yazses.perception.signals import GazeSignal, PerceptionSample


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Layout:
    """A fingerprint the test sets by hand; ``None`` is "cannot read the layout"."""

    def __init__(self, value: str | None = "layout-A") -> None:
        self.value = value
        self.reads = 0
        self.raise_next = False

    def __call__(self) -> str | None:
        self.reads += 1
        if self.raise_next:
            self.raise_next = False
            raise OSError("display server went away")
        return self.value


def capture(**kwargs):
    got: list = []
    return got, ClickGazeCapture(got.append, **kwargs)


# --------------------------------------------------------------------------- #
# The ring is bounded in age
# --------------------------------------------------------------------------- #


def test_the_default_age_bound_is_never_shorter_than_the_look_back() -> None:
    assert DEFAULT_MAX_AGE_S >= DEFAULT_LOOKBACK_S
    _, cap = capture()
    assert cap.history.max_age_s == DEFAULT_MAX_AGE_S
    wide = AssociationPolicy(latency_s=0.1, lookback_s=DEFAULT_MAX_AGE_S + 1.0)
    _, cap = capture(policy=wide)
    assert cap.history.max_age_s == DEFAULT_MAX_AGE_S + 1.0


def test_a_face_that_leaves_the_frame_ages_out_of_ram_while_no_face_arrives() -> None:
    clock = Clock(1000.0)
    _, cap = capture(clock=clock)
    for i in range(10):
        cap.record_gaze(gaze(1000.0 + i * 0.05))
    assert len(cap.history) == 10
    clock.now = 1000.45 + DEFAULT_MAX_AGE_S + 0.01   # every sample now older than the bound
    cap.record_gaze(None)                              # the poller sees no face
    assert len(cap.history) == 0, "old eye positions outlived the age bound"


def test_a_ring_emptied_by_age_says_stale_not_no_gaze() -> None:
    clock = Clock(1000.0)
    got, cap = capture(clock=clock)
    cap.record_gaze(gaze(999.9))
    clock.now = 1000.0 + DEFAULT_MAX_AGE_S + 1.0
    result = cap.handle_click(ClickEvent(clock.now, 1.0, 1.0))
    assert result.reason is RejectReason.STALE
    assert cap.stats() == CaptureStats(clicks=1, stale=1)
    assert got == []


def test_a_ring_that_never_saw_a_face_still_says_no_gaze() -> None:
    _, cap = capture(clock=Clock(1000.0))
    cap.record_gaze(None)
    assert cap.handle_click(ClickEvent(1000.0, 1.0, 1.0)).reason is RejectReason.NO_GAZE


def test_the_age_bound_never_drops_a_sample_the_look_back_allows() -> None:
    policy = AssociationPolicy(latency_s=0.1, lookback_s=3.0)
    clock = Clock(1000.0)
    got, cap = capture(policy=policy, clock=clock)
    cap.record_gaze(gaze(1000.0))
    clock.now = 1002.9
    cap.record_gaze(None)
    assert cap.handle_click(ClickEvent(1002.9, 1.0, 1.0)).accepted
    assert len(got) == 1


def test_without_a_clock_the_ring_ages_against_each_new_sample() -> None:
    _, cap = capture()
    cap.record_gaze(gaze(10.0))
    cap.record_gaze(gaze(10.0 + DEFAULT_MAX_AGE_S + 0.5))
    assert [s.timestamp_s for s in cap.history.snapshot()] == [10.0 + DEFAULT_MAX_AGE_S + 0.5]


def test_an_injected_ring_shorter_than_the_look_back_is_refused() -> None:
    with pytest.raises(ValueError, match="look-back"):
        ClickGazeCapture(lambda _: None, history=GazeHistory(max_age_s=0.2))
    # An unbounded-in-age ring is the old behaviour and stays legal.
    ClickGazeCapture(lambda _: None, history=GazeHistory())


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_a_nonsense_age_bound_is_refused(bad: float) -> None:
    with pytest.raises(ValueError):
        GazeHistory(max_age_s=bad)


def test_prune_counts_what_it_dropped_and_clear_forgets_that_it_did() -> None:
    ring = GazeHistory(max_age_s=1.0)
    for t in (1.0, 2.0, 3.0):
        ring.record(gaze(t))
    assert ring.prune(3.5) == 2 and ring.aged_out
    assert ring.prune(math.nan) == 0, "a non-finite now must not empty the ring"
    assert [s.timestamp_s for s in ring.snapshot()] == [3.0]
    ring.clear()
    assert not ring.aged_out and len(ring) == 0


def test_a_ring_without_an_age_bound_never_prunes() -> None:
    ring = GazeHistory()
    ring.record(gaze(1.0))
    assert ring.prune(1e9) == 0 and len(ring) == 1 and not ring.aged_out


# --------------------------------------------------------------------------- #
# A changed layout drops the ring
# --------------------------------------------------------------------------- #


def test_a_layout_change_drops_the_ring_and_refuses_the_click_that_saw_it(caplog) -> None:
    layout = Layout("layout-A")
    got, cap = capture(fingerprint=layout)
    cap.record_gaze(gaze(99.9))
    assert cap.handle_click(ClickEvent(100.0, 1.0, 1.0)).accepted     # baseline adopted
    cap.record_gaze(gaze(100.9))                                      # recorded in layout A...
    layout.value = "layout-B"                                         # ...monitor unplugged
    with caplog.at_level(logging.INFO, logger="yazses.gaze.capture"):
        result = cap.handle_click(ClickEvent(101.0, 640.0, 360.0))
    assert result.reason is RejectReason.TOPOLOGY_CHANGED
    assert len(cap.history) == 0 and len(cap._used) == 0
    assert len(got) == 1, "a click in the new layout was paired with the old layout's eyes"
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "layout" in text
    assert "layout-B" not in text and "640" not in text, "a fingerprint or position was logged"


def test_after_a_change_only_gaze_seen_since_can_pair() -> None:
    layout = Layout("layout-A")
    got, cap = capture(fingerprint=layout)
    cap.record_gaze(gaze(99.9))
    cap.handle_click(ClickEvent(100.0, 1.0, 1.0))
    layout.value = "layout-B"
    assert cap.handle_click(ClickEvent(100.5, 1.0, 1.0)).reason is RejectReason.TOPOLOGY_CHANGED
    assert cap.handle_click(ClickEvent(100.6, 1.0, 1.0)).reason is RejectReason.NO_GAZE
    cap.record_gaze(gaze(100.9, x=0.7))
    assert cap.handle_click(ClickEvent(101.0, 2.0, 2.0)).accepted
    assert [p.gaze[0] for p in got] == [0.1, 0.7]
    stats = cap.stats()
    assert (stats.topology_changed, stats.no_gaze, stats.accepted) == (1, 1, 2)
    assert stats.rejected == 2


def test_a_change_and_a_change_back_are_two_changes() -> None:
    layout = Layout("docked")
    _, cap = capture(fingerprint=layout)
    cap.handle_click(ClickEvent(100.0, 1.0, 1.0))
    for value in ("undocked", "docked"):
        layout.value = value
        assert cap.handle_click(ClickEvent(101.0, 1.0, 1.0)).reason is RejectReason.TOPOLOGY_CHANGED
    assert cap.stats().topology_changed == 2


def test_the_same_layout_read_again_drops_nothing() -> None:
    layout = Layout("layout-A")
    got, cap = capture(fingerprint=layout)
    for i in range(5):
        cap.record_gaze(gaze(100.0 + i))
        assert cap.handle_click(ClickEvent(100.1 + i, 1.0, 1.0)).accepted
    assert len(got) == 5 and cap.stats().topology_changed == 0


def test_an_unreadable_layout_is_not_a_change() -> None:
    layout = Layout("layout-A")
    got, cap = capture(fingerprint=layout)
    cap.handle_click(ClickEvent(100.0, 1.0, 1.0))                     # baseline
    cap.record_gaze(gaze(100.9))
    layout.value = None                                               # xrandr failed
    assert cap.handle_click(ClickEvent(101.0, 1.0, 1.0)).accepted
    layout.value = "layout-A"
    layout.raise_next = True                                          # the reader raised
    cap.record_gaze(gaze(101.9))
    assert cap.handle_click(ClickEvent(102.0, 1.0, 1.0)).accepted
    assert len(got) == 2 and cap.stats().topology_changed == 0


def test_the_first_readable_layout_is_the_baseline_not_a_change() -> None:
    layout = Layout(None)
    got, cap = capture(fingerprint=layout)
    cap.record_gaze(gaze(99.9))
    assert cap.handle_click(ClickEvent(100.0, 1.0, 1.0)).accepted     # unknown: no baseline
    layout.value = "layout-A"
    cap.record_gaze(gaze(100.9))
    assert cap.handle_click(ClickEvent(101.0, 1.0, 1.0)).accepted     # adopted, not a change
    assert cap.stats().topology_changed == 0


def test_without_a_fingerprint_the_capture_does_not_watch_the_layout() -> None:
    _, cap = capture()
    assert cap.observe_topology() is False


def test_the_service_takes_its_baseline_at_start_so_the_first_click_can_see_a_change() -> None:
    layout = Layout("layout-A")
    got: list = []
    cap = ClickGazeCapture(got.append, fingerprint=layout)
    observer, lease = FakeObserver(), FakeLease()
    svc = ImplicitCaptureService(capture=cap, observer=observer, lease=lease)
    svc.start()
    assert layout.reads == 1
    lease.sample = PerceptionSample(99.9, gaze=GazeSignal(99.9, 0.1, 0.2, 0.9))
    svc.poll()
    layout.value = "layout-B"                         # changed before the very first click
    observer.click(100.0)
    assert got == [] and cap.stats().topology_changed == 1
    svc.stop()


# --------------------------------------------------------------------------- #
# The throttled reader
# --------------------------------------------------------------------------- #


def test_a_burst_of_clicks_reads_the_layout_once_per_interval() -> None:
    clock = Clock(0.0)
    layout = Layout("layout-A")
    watch = ThrottledFingerprint(layout, min_interval_s=1.0, clock=clock)
    for _ in range(100):
        assert watch() == "layout-A"
    assert layout.reads == 1 and watch.reads == 1
    clock.now = 0.99
    watch()
    assert layout.reads == 1
    clock.now = 1.0
    layout.value = "layout-B"
    assert watch() == "layout-B" and layout.reads == 2


def test_a_seed_is_the_first_answer_and_costs_no_read() -> None:
    clock = Clock(0.0)
    layout = Layout("layout-B")
    watch = ThrottledFingerprint(layout, min_interval_s=1.0, clock=clock, seed="layout-A")
    assert watch() == "layout-A" and layout.reads == 0
    clock.now = 1.5
    assert watch() == "layout-B" and layout.reads == 1


def test_a_failed_or_empty_read_keeps_the_last_known_layout() -> None:
    clock = Clock(0.0)
    layout = Layout("layout-A")
    watch = ThrottledFingerprint(layout, min_interval_s=0.0, clock=clock)
    assert watch() == "layout-A"
    layout.value = None
    assert watch() == "layout-A"
    layout.raise_next = True
    assert watch() == "layout-A"


@pytest.mark.parametrize("bad", [-1.0, math.nan, math.inf])
def test_a_nonsense_interval_is_refused(bad: float) -> None:
    with pytest.raises(ValueError):
        ThrottledFingerprint(lambda: "x", min_interval_s=bad)


# --------------------------------------------------------------------------- #
# The real context fingerprint, and the wiring
# --------------------------------------------------------------------------- #


def _context(*displays: Display, camera: str = "0") -> CalibrationContext:
    return CalibrationContext(topology=DisplayTopology(displays), camera_id=camera)


LAPTOP = Display("eDP-1", 0, 0, 1920, 1080, scale=2.0, primary=True)
LEFT = Display("HDMI-1", -2560, 0, 2560, 1440)


def test_the_watch_reads_the_adr_149_fingerprint_and_unknown_is_none() -> None:
    current = {"ctx": _context(LAPTOP)}
    clock = Clock(0.0)
    watch = context_fingerprint(lambda: current["ctx"], accepted=_context(LAPTOP), clock=clock)
    assert watch() == _context(LAPTOP).fingerprint()
    clock.now = 10.0
    current["ctx"] = _context()                        # topology could not be read
    assert watch() == _context(LAPTOP).fingerprint(), "an unknown layout read as a change"
    clock.now = 20.0
    current["ctx"] = _context(LAPTOP, LEFT)            # a negative-origin monitor plugged in
    assert watch() == _context(LAPTOP, LEFT).fingerprint()
    clock.now = 30.0
    current["ctx"] = _context(LAPTOP, camera="1")      # a different camera
    assert watch() == _context(LAPTOP, camera="1").fingerprint()


def test_an_unknown_accepted_context_seeds_nothing() -> None:
    reads: list = []
    watch = context_fingerprint(
        lambda: reads.append(1) or _context(LAPTOP), accepted=_context(), clock=Clock(0.0)
    )
    assert watch() == _context(LAPTOP).fingerprint() and reads == [1]


def test_the_runtime_builder_hands_the_fingerprint_to_the_capture(tmp_path) -> None:
    from tests.test_gaze_refine_runtime import build

    layout = Layout("layout-A")
    runtime, reason, _, _, _ = build(tmp_path, fingerprint=layout)
    assert runtime is not None, reason
    try:
        assert layout.reads == 1, "the service did not take its baseline at start"
        runtime.capture.record_gaze(gaze(99.9))
        layout.value = "layout-B"
        result = runtime.capture.handle_click(ClickEvent(100.0, 1.0, 1.0))
        assert result.reason is RejectReason.TOPOLOGY_CHANGED
    finally:
        runtime.stop()


def test_the_daemon_passes_its_layout_watch_to_the_capture() -> None:
    from tests.test_gaze_refine_wiring import FakeObserver as WiringObserver
    from tests.test_gaze_refine_wiring import _daemon

    daemon = _daemon(observer=WiringObserver())
    assert daemon._gaze_context_fingerprint is None, "a default daemon must watch nothing"
    layout = Layout("layout-A")
    daemon._gaze_context_fingerprint = layout
    runtime = daemon._build_gaze_refinement(daemon._config)
    assert runtime is not None
    try:
        assert runtime.capture._fingerprint is layout
    finally:
        runtime.stop()


# --------------------------------------------------------------------------- #
# What is held: numbers only
# --------------------------------------------------------------------------- #


def test_the_counters_are_integers_only_including_the_new_one() -> None:
    layout = Layout("layout-A")
    _, cap = capture(fingerprint=layout)
    cap.handle_click(ClickEvent(100.0, 1.0, 1.0))
    layout.value = "layout-B"
    cap.handle_click(ClickEvent(101.0, 1.0, 1.0))
    stats = cap.stats()
    for f in dataclasses.fields(stats):
        assert type(getattr(stats, f.name)) is int, f.name
    assert stats.topology_changed == 1
