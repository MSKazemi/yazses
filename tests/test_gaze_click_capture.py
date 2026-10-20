"""Click + gaze capture for implicit calibration: pairing, rejection, opt-in (#397).

``gaze/implicit.py`` could already refine a calibration from ``(gaze, click)`` pairs, but
nothing produced pairs (issue #101 was closed before the capture path existed). These
tests pin the missing seam. What is worth a test here is not the arithmetic, it is the
*refusals*, because a pairing that accepts a bad pair is worse than no pairing — the user
cannot see the map move:

* a missing, stale or low-confidence gaze sample is rejected **with a named reason**;
* a rejected nearest sample is never replaced by a farther, better one (that would pair a
  click with the eyes of a different moment);
* a sample recorded *after* the click is never used;
* every empty case (empty ring, no face, no clicks) is defined and tested, because a guard
  that iterates is green on an empty collection;
* the click value and the pair carry coordinates and numbers and **nothing else** — no
  field exists that could hold a window title, a typed character or a frame.

The thresholds used below are synthetic stream parameters chosen to exercise boundaries.
None is a claim about what a person's eyes do: the aim latency and look-back are unmeasured
starting values (see ``gaze/association.py``) and field evidence (#104) is what sets them.

Hermetic: a fake click observer, a fake lease and numeric gaze streams. No desktop, no
camera, no network, no thread unless a test says so.
"""
from __future__ import annotations

import ast
import dataclasses
import random
import threading
from pathlib import Path

import pytest

import yazses.gaze.association as association_module
import yazses.gaze.capture as capture_module
import yazses.gaze.clicks as clicks_module
from yazses.gaze.association import (
    Association,
    AssociationPolicy,
    GazeHistory,
    RejectReason,
    associate,
)
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.capture import CaptureStats, ClickGazeCapture, ImplicitCaptureService
from yazses.gaze.clicks import ClickEvent, ClickObserver, ClickObserverError
from yazses.gaze.implicit import ImplicitCalibrator
from yazses.perception.signals import GazeSignal, PerceptionSample

# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


def gaze(t: float, x: float = 0.1, y: float = 0.2, confidence: float = 0.9) -> GazeSignal:
    return GazeSignal(timestamp_s=t, raw_x=x, raw_y=y, confidence=confidence)


class FakeObserver:
    """A click observer made of a callback slot; the test is the user's hand."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.callback = None
        self.starts = 0
        self.stops = 0
        self._fail_with = fail_with

    def start(self, on_click) -> None:
        self.starts += 1
        if self._fail_with is not None:
            raise self._fail_with
        self.callback = on_click

    def stop(self) -> None:
        self.stops += 1
        self.callback = None

    def click(self, t: float, x: float = 500.0, y: float = 400.0):
        assert self.callback is not None, "the observer is not started: no click can arrive"
        return self.callback(ClickEvent(t, x, y))


class FakeLease:
    """``FacePerceptionSource`` as a consumer sees it, serving whatever it is told to."""

    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0
        self.sample: PerceptionSample | None = None

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1

    def latest(self):
        return self.sample


def collecting() -> tuple[list[Association], ClickGazeCapture]:
    got: list[Association] = []
    return got, ClickGazeCapture(got.append)


# --------------------------------------------------------------------------- #
# The click value: where and when, structurally nothing else
# --------------------------------------------------------------------------- #


def test_a_click_carries_exactly_a_time_and_a_place() -> None:
    names = {f.name for f in dataclasses.fields(ClickEvent)}
    assert names == {"timestamp_s", "x", "y"}, (
        "a click grew a field; implicit calibration must never be able to hold a window "
        "title, a button, an application name or typed text"
    )


def test_negative_coordinates_are_legal_for_a_monitor_left_of_the_primary() -> None:
    click = ClickEvent(10.0, -1280.0, -40.0)
    assert (click.x, click.y) == (-1280.0, -40.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["timestamp_s", "x", "y"])
def test_a_non_finite_click_is_refused_at_the_boundary(field: str, bad: float) -> None:
    kwargs = {"timestamp_s": 1.0, "x": 2.0, "y": 3.0, field: bad}
    with pytest.raises(ValueError, match=field):
        ClickEvent(**kwargs)


def test_the_observer_protocol_is_satisfied_by_the_fake_and_nothing_vacuous() -> None:
    assert isinstance(FakeObserver(), ClickObserver)
    assert not isinstance(object(), ClickObserver)


def test_the_platform_carries_an_optional_click_observer_factory_that_defaults_to_none() -> None:
    """The seam: a platform without a backend says so by having none, not by a fake that
    accepts a start() and never delivers a click."""
    from yazses.platform.base import Platform

    by_name = {f.name: f for f in dataclasses.fields(Platform)}
    assert "click_observer_factory" in by_name
    assert by_name["click_observer_factory"].default is None


# --------------------------------------------------------------------------- #
# The policy
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "kwargs",
    [
        {"latency_s": -0.01},
        {"lookback_s": 0.0},
        {"lookback_s": -1.0},
        {"latency_s": 0.6, "lookback_s": 0.5},     # the aim point would lie outside the window
        {"min_confidence": -0.1},
        {"min_confidence": 1.1},
        {"latency_s": float("nan")},
        {"lookback_s": float("inf")},
        {"min_confidence": float("nan")},
    ],
)
def test_a_nonsense_policy_is_refused_when_built(kwargs) -> None:
    with pytest.raises(ValueError):
        AssociationPolicy(**kwargs)


def test_zero_latency_and_a_latency_equal_to_the_lookback_are_legal_edges() -> None:
    AssociationPolicy(latency_s=0.0)
    AssociationPolicy(latency_s=0.5, lookback_s=0.5)


# --------------------------------------------------------------------------- #
# associate(): choosing the sample
# --------------------------------------------------------------------------- #

CLICK = ClickEvent(100.0, 640.0, 360.0)
POLICY = AssociationPolicy(latency_s=0.1, lookback_s=0.5, min_confidence=0.5)


def test_it_picks_the_sample_nearest_the_aim_point_not_the_newest_or_the_oldest() -> None:
    samples = [gaze(99.55, x=0.01), gaze(99.88, x=0.02), gaze(99.99, x=0.04)]
    result = associate(CLICK, samples, POLICY)  # aim point = 99.90
    assert result.accepted and result.association is not None
    assert result.association.gaze[0] == 0.02


# Binary-exact times, so "equally far from the aim point" is exactly equal and not a
# floating-point coin toss: the aim point is 99.875 and 99.75 / 100.0 are each 0.125 away.
EXACT = AssociationPolicy(latency_s=0.125, lookback_s=0.5, min_confidence=0.5)
EXACT_TIE = [gaze(99.75, x=0.01), gaze(100.0, x=0.02), gaze(99.5, x=0.03)]


def test_a_tie_goes_to_the_earlier_sample() -> None:
    result = associate(CLICK, EXACT_TIE, EXACT)
    assert result.association is not None and result.association.gaze[0] == 0.01


def test_ties_resolve_the_same_way_whatever_order_the_samples_arrive_in() -> None:
    answers = {
        associate(CLICK, shuffled, EXACT).association.gaze  # type: ignore[union-attr]
        for shuffled in (
            random.Random(seed).sample(EXACT_TIE, len(EXACT_TIE)) for seed in range(12)
        )
    }
    assert len(answers) == 1


def test_the_pair_carries_the_gaze_the_click_the_confidence_and_the_lag() -> None:
    result = associate(CLICK, [gaze(99.9, x=0.3, y=-0.2, confidence=0.8)], POLICY)
    assert result.association == Association(
        gaze=(0.3, -0.2),
        click=(640.0, 360.0),
        confidence=0.8,
        lag_s=pytest.approx(0.1),
        gaze_timestamp_s=99.9,
    )
    assert result.reason is None


def test_a_changed_latency_moves_which_sample_is_chosen() -> None:
    samples = [gaze(99.5, x=0.1), gaze(99.9, x=0.2)]
    early = associate(CLICK, samples, AssociationPolicy(latency_s=0.5, lookback_s=0.5))
    late = associate(CLICK, samples, AssociationPolicy(latency_s=0.1, lookback_s=0.5))
    assert early.association.gaze[0] == 0.1  # type: ignore[union-attr]
    assert late.association.gaze[0] == 0.2  # type: ignore[union-attr]


# --- the window: boundaries, and never forward in time ---------------------------


def test_a_sample_exactly_at_the_lookback_edge_is_inside_and_a_hair_older_is_stale() -> None:
    inside = associate(CLICK, [gaze(99.5)], POLICY)
    outside = associate(CLICK, [gaze(99.4999)], POLICY)
    assert inside.accepted
    assert outside.reason is RejectReason.STALE


def test_a_sample_stamped_at_the_click_instant_counts_but_one_after_it_never_does() -> None:
    assert associate(CLICK, [gaze(100.0)], POLICY).accepted
    after = associate(CLICK, [gaze(100.001)], POLICY)
    assert after.reason is RejectReason.STALE, (
        "an eye position recorded after the button went down cannot be what aimed it"
    )


def test_only_post_click_samples_are_stale_not_no_gaze() -> None:
    result = associate(CLICK, [gaze(100.2), gaze(100.4)], POLICY)
    assert result.reason is RejectReason.STALE


def test_old_samples_beside_a_usable_one_do_not_get_in_the_way() -> None:
    result = associate(CLICK, [gaze(90.0, x=0.9), gaze(99.9, x=0.1)], POLICY)
    assert result.association is not None and result.association.gaze[0] == 0.1


# --- the empty and the refusals ---------------------------------------------------


def test_no_samples_at_all_is_no_gaze() -> None:
    result = associate(CLICK, [], POLICY)
    assert result.association is None and result.reason is RejectReason.NO_GAZE
    assert not result.accepted


def test_a_generator_of_nothing_is_the_same_as_an_empty_list() -> None:
    assert associate(CLICK, (s for s in ()), POLICY).reason is RejectReason.NO_GAZE


def test_only_stale_samples_is_stale_not_no_gaze() -> None:
    assert associate(CLICK, [gaze(10.0), gaze(11.0)], POLICY).reason is RejectReason.STALE


def test_a_low_confidence_nearest_sample_is_rejected() -> None:
    result = associate(CLICK, [gaze(99.9, confidence=0.49)], POLICY)
    assert result.reason is RejectReason.LOW_CONFIDENCE


def test_confidence_equal_to_the_floor_is_accepted() -> None:
    assert associate(CLICK, [gaze(99.9, confidence=0.5)], POLICY).accepted


def test_a_poor_nearest_sample_is_not_swapped_for_a_better_farther_one() -> None:
    """The eyes disagreed at the moment that matters. A confident sample 0.35 s earlier
    describes where the user was looking *then*, and pairing it with this click would teach
    the map the wrong thing with a perfectly good-looking confidence."""
    samples = [gaze(99.55, x=0.7, confidence=0.99), gaze(99.9, x=0.1, confidence=0.2)]
    result = associate(CLICK, samples, POLICY)
    assert result.association is None
    assert result.reason is RejectReason.LOW_CONFIDENCE


def test_a_zero_confidence_floor_accepts_any_confidence_including_zero() -> None:
    result = associate(CLICK, [gaze(99.9, confidence=0.0)], AssociationPolicy(min_confidence=0.0))
    assert result.accepted


# --------------------------------------------------------------------------- #
# The gaze ring
# --------------------------------------------------------------------------- #


def test_the_ring_ignores_none_duplicates_and_out_of_order_samples() -> None:
    ring = GazeHistory(capacity=8)
    assert ring.record(None) is False
    assert ring.record(gaze(1.0)) is True
    assert ring.record(gaze(1.0)) is False          # the poller read the same frame twice
    assert ring.record(gaze(0.5)) is False          # an older sample cannot arrive later
    assert ring.record(gaze(1.1)) is True
    assert [s.timestamp_s for s in ring.snapshot()] == [1.0, 1.1]
    assert len(ring) == 2


def test_the_ring_is_bounded_and_drops_the_oldest() -> None:
    ring = GazeHistory(capacity=3)
    for i in range(10):
        ring.record(gaze(float(i)))
    assert [s.timestamp_s for s in ring.snapshot()] == [7.0, 8.0, 9.0]


def test_an_empty_ring_snapshots_to_an_empty_tuple() -> None:
    assert GazeHistory().snapshot() == ()
    assert len(GazeHistory()) == 0


def test_a_ring_needs_room_for_at_least_one_sample() -> None:
    with pytest.raises(ValueError):
        GazeHistory(capacity=0)


def test_clear_forgets_everything() -> None:
    ring = GazeHistory()
    ring.record(gaze(1.0))
    ring.clear()
    assert ring.snapshot() == ()
    assert ring.record(gaze(0.5)) is True, "after a clear an earlier timestamp is new again"


def test_the_ring_survives_a_writer_and_a_reader_on_two_threads() -> None:
    ring = GazeHistory(capacity=16)
    stop = threading.Event()
    seen_lengths: list[int] = []

    def reader() -> None:
        while not stop.is_set():
            seen_lengths.append(len(ring.snapshot()))

    thread = threading.Thread(target=reader)
    thread.start()
    for i in range(2000):
        ring.record(gaze(float(i)))
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert max(seen_lengths or [0]) <= 16


# --------------------------------------------------------------------------- #
# ClickGazeCapture: fake click + gaze streams end to end
# --------------------------------------------------------------------------- #


def test_a_click_with_recent_confident_gaze_reaches_the_sink() -> None:
    got, capture = collecting()
    capture.record_gaze(gaze(99.9, x=0.25, y=-0.1, confidence=0.9))
    result = capture.handle_click(ClickEvent(100.0, 800.0, 450.0))
    assert result.accepted
    assert len(got) == 1
    assert got[0].gaze == (0.25, -0.1) and got[0].click == (800.0, 450.0)
    assert capture.stats() == CaptureStats(clicks=1, accepted=1)


def test_every_rejection_is_counted_under_its_own_reason_and_never_reaches_the_sink() -> None:
    got, capture = collecting()
    capture.handle_click(ClickEvent(100.0, 1.0, 1.0))            # nothing recorded yet
    capture.record_gaze(gaze(50.0))
    capture.handle_click(ClickEvent(100.0, 1.0, 1.0))            # only a stale sample
    capture.record_gaze(gaze(99.9, confidence=0.1))
    capture.handle_click(ClickEvent(100.0, 1.0, 1.0))            # nearest sample is poor
    stats = capture.stats()
    assert got == []
    assert (stats.clicks, stats.accepted) == (3, 0)
    assert (stats.no_gaze, stats.stale, stats.low_confidence) == (1, 1, 1)
    assert stats.rejected == 3


def test_no_clicks_means_zero_everything_not_a_division_or_a_crash() -> None:
    _, capture = collecting()
    stats = capture.stats()
    assert stats == CaptureStats()
    assert stats.rejected == 0


def test_a_face_that_leaves_the_frame_makes_later_clicks_stale() -> None:
    got, capture = collecting()
    capture.record_gaze(gaze(99.9))
    assert capture.handle_click(ClickEvent(100.0, 1.0, 1.0)).accepted
    capture.record_gaze(None)  # no face this poll: nothing is recorded, nothing is replayed
    result = capture.handle_click(ClickEvent(105.0, 1.0, 1.0))
    assert result.reason is RejectReason.STALE
    assert len(got) == 1


def test_a_failing_sink_is_contained_so_the_input_hook_survives() -> None:
    def boom(_: Association) -> None:
        raise RuntimeError("estimator exploded")

    capture = ClickGazeCapture(boom)
    capture.record_gaze(gaze(99.9))
    assert capture.handle_click(ClickEvent(100.0, 1.0, 1.0)).accepted  # no exception escapes


def test_an_accepted_pair_is_numbers_only() -> None:
    _, capture = collecting()
    capture.record_gaze(gaze(99.9))
    pair = capture.handle_click(ClickEvent(100.0, 1.0, 2.0)).association
    assert pair is not None
    for field in dataclasses.fields(pair):
        value = getattr(pair, field.name)
        flat = value if isinstance(value, tuple) else (value,)
        assert all(isinstance(v, float) for v in flat), f"{field.name} holds a non-number"


# --------------------------------------------------------------------------- #
# The service: opt-in lifecycle around an observer and a lease
# --------------------------------------------------------------------------- #


def service(*, observer=None, lease=None, sink=None):
    observer = observer or FakeObserver()
    lease = lease or FakeLease()
    got: list[Association] = []
    capture = ClickGazeCapture(sink or got.append)
    return ImplicitCaptureService(capture=capture, observer=observer, lease=lease), observer, lease, got


def test_building_the_service_touches_neither_the_camera_nor_the_desktop() -> None:
    svc, observer, lease, _ = service()
    assert (observer.starts, lease.starts) == (0, 0)
    assert svc.running is False


def test_start_takes_the_lease_and_the_hook_and_stop_gives_both_back() -> None:
    svc, observer, lease, _ = service()
    svc.start()
    assert (lease.starts, observer.starts) == (1, 1) and svc.running
    svc.stop()
    assert (lease.stops, observer.stops) == (1, 1) and not svc.running


def test_start_and_stop_are_idempotent() -> None:
    svc, observer, lease, _ = service()
    svc.start()
    svc.start()
    assert (lease.starts, observer.starts) == (1, 1)
    svc.stop()
    svc.stop()
    assert (lease.stops, observer.stops) == (1, 1)


def test_stop_before_start_does_nothing() -> None:
    svc, observer, lease, _ = service()
    svc.stop()
    assert (lease.stops, observer.stops) == (0, 0)


def test_a_hook_that_cannot_be_installed_releases_the_camera_and_says_why() -> None:
    """A camera held for a feature that can never receive a click is the silent
    webcam-light leak the shared source exists to end."""
    svc, observer, lease, _ = service(
        observer=FakeObserver(fail_with=ClickObserverError("no click hook on this session"))
    )
    with pytest.raises(ClickObserverError, match="no click hook"):
        svc.start()
    assert lease.starts == 1 and lease.stops == 1
    assert svc.running is False


def test_poll_copies_the_shared_sources_newest_gaze_into_the_ring_once() -> None:
    svc, _, lease, _ = service()
    svc.start()
    assert svc.poll() is False                       # nothing from the camera yet
    lease.sample = PerceptionSample(5.0, gaze=gaze(5.0))
    assert svc.poll() is True
    assert svc.poll() is False                       # the same observation is not a new one
    lease.sample = PerceptionSample(5.1)             # a frame with no gaze channel
    assert svc.poll() is False


def test_a_click_after_stop_cannot_arrive_and_the_recent_gaze_is_forgotten() -> None:
    svc, observer, lease, got = service()
    svc.start()
    lease.sample = PerceptionSample(99.9, gaze=gaze(99.9))
    svc.poll()
    svc.stop()
    assert observer.callback is None
    assert svc._capture.history.snapshot() == ()
    assert got == []


def test_run_polls_until_stopped_and_then_returns() -> None:
    svc, _, lease, _ = service()
    svc.start()
    stop = threading.Event()
    polls = {"n": 0}
    real_latest = lease.latest

    def latest():
        polls["n"] += 1
        if polls["n"] >= 3:
            stop.set()
        return real_latest()

    lease.latest = latest  # type: ignore[method-assign]
    thread = threading.Thread(target=svc.run, args=(stop,))
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert polls["n"] >= 3


def test_the_whole_path_from_a_fake_click_to_the_estimator() -> None:
    """Fake gaze stream + fake clicks -> accepted pairs update a real ImplicitCalibrator;
    a stale, a low-confidence and a no-face click leave it untouched."""
    truth = CalibrationMap(A=_affine())
    estimator = ImplicitCalibrator(baseline=truth)
    observer, lease = FakeObserver(), FakeLease()
    capture = ClickGazeCapture(
        lambda pair: estimator.observe(pair.gaze, pair.click, confidence=pair.confidence)
    )
    svc = ImplicitCaptureService(capture=capture, observer=observer, lease=lease)
    svc.start()

    def see(t: float, confidence: float = 0.9, x: float = 0.1, y: float = 0.1) -> None:
        lease.sample = PerceptionSample(t, gaze=GazeSignal(t, x, y, confidence))
        svc.poll()

    see(10.0)
    px, py = truth.predict(0.1, 0.1)
    observer.click(10.1, px, py)                     # good: accepted
    assert estimator.accepted == 1

    observer.click(60.0, px, py)                     # long after the last sample: stale
    see(70.0, confidence=0.1)
    observer.click(70.1, px, py)                     # nearest sample is poor
    assert estimator.accepted == 1 and estimator.rejected == 0, (
        "rejected pairs must be stopped at the association gate, not reach the estimator"
    )
    stats = capture.stats()
    assert (stats.clicks, stats.accepted, stats.stale, stats.low_confidence) == (3, 1, 1, 1)
    svc.stop()


def _affine():
    import numpy as np

    return np.array([[900.0, 0.0, 960.0], [0.0, 700.0, 540.0]])


# --------------------------------------------------------------------------- #
# Structure: standard library and numbers only
# --------------------------------------------------------------------------- #

_FORBIDDEN_IMPORTS = {
    "socket", "ssl", "http", "urllib", "requests", "httpx", "subprocess", "ftplib", "smtplib",
    "cv2", "mediapipe", "PIL", "pyautogui", "pynput", "Xlib", "mss", "pyperclip",
}


@pytest.mark.parametrize("module", [clicks_module, association_module, capture_module])
def test_capture_modules_import_no_network_screen_or_camera_library(module) -> None:
    """Nothing leaves the machine and nothing is captured but numbers (AGENTS.md rule 1)."""
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(_FORBIDDEN_IMPORTS), sorted(imported & _FORBIDDEN_IMPORTS)
