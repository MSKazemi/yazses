"""The semantic-grounding seam is additive: absent it, gaze behaves exactly as before.

ADR-v2-151 phase P2 (`design/specs/eye-grounded-targets.md`). The feature being added is
small — a coarse looked-at window can be refined to one exact UI element — and the thing
that matters more is everything that must *not* change: Glance-Type window routing, the
low-confidence fallback, and the destructive confirm/ignore semantics of window deixis.

So most of this file is regression pressure rather than feature coverage. The pattern
throughout is a paired run: the same backend, calibration, desktop and gaze sample driven
once with no grounder and once with one, asserting the two `RouteDecision`s are equal.
That is the acceptance criterion stated as an experiment instead of as an opinion — a
seam that changed routing could not pass it whatever its own tests said.

Everything is a fake. No camera, no X11, no accessibility library, no network: the
semantic source is a list of values, which is the whole reason ADR-v2-151 put the
platform adapters behind a Protocol.
"""
from __future__ import annotations

import ast
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from yazses.config import Config, GazeConfig
from yazses.core.daemon import Daemon
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.confidence import GazeSample
from yazses.gaze.grounded import SCREEN_SPACE, GazeGrounder, RefinedTarget, refine
from yazses.gaze.route import RouteDecision
from yazses.gaze.targeter import GazeTargeter
from yazses.grounding import (
    CoordinateSpace,
    GroundingOutcome,
    GroundingResult,
    IntentHint,
    Point,
    Rect,
    ResolutionPolicy,
    SemanticCandidate,
    SemanticSourceKind,
    TargetResolver,
    TargetSnapshot,
    TargetSource,
    UnresolvedReason,
)

#: A fixed clock reading. Injected everywhere so a slow machine cannot make a target
#: stale mid-test — the freshness budget is real policy and deserves its own tests
#: (below), not a flake in every other one.
NOW = 100.0


# ---- fakes ------------------------------------------------------------------


class _SampleBackend:
    """The mediapipe backend shape: one `GazeSample` with a real confidence."""

    def __init__(self, *samples):
        self._samples = list(samples)
        self.closed = False

    def estimate_sample(self):
        return self._samples.pop(0) if self._samples else None

    def close(self):
        self.closed = True


class _FakeDesktop:
    def __init__(self, focused, windows):
        self._focused = focused
        self._windows = windows
        self.activated = []
        self.closed = []
        self.minimized = []

    def focused_window(self):
        return self._focused

    def list_windows(self):
        return self._windows

    def activate(self, wid):
        self.activated.append(wid)

    def close(self, wid):
        self.closed.append(wid)

    def minimize(self, wid):
        self.minimized.append(wid)


class _FakeSource:
    """A semantic source that is a list of values, and records what it was asked."""

    def __init__(self, *candidates):
        self._candidates = list(candidates)
        self.calls = []

    def snapshot(self, *, window_id, region):
        self.calls.append((window_id, region))
        return list(self._candidates)


class _BoomSource:
    """The platform adapter of the real world: it raises."""

    def __init__(self, exc=None):
        self._exc = exc or RuntimeError("AT-SPI registry is not running")
        self.calls = 0

    def snapshot(self, *, window_id, region):
        self.calls += 1
        raise self._exc


def _identity_cal():
    # predict(x, y) == (x, y): the screen point equals the gaze angle, as in
    # `tests/test_gaze_wiring.py`, so a sample's coordinates are readable as pixels.
    return CalibrationMap(A=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]))


def _two_panes():
    return [("editor", 0, 0, 500, 1000), ("browser", 500, 0, 500, 1000)]


def _candidate(entity_id, bounds, *, role="button", label=None, kind=None, captured_at=NOW):
    return SemanticCandidate(
        source=kind or SemanticSourceKind.ACCESSIBILITY,
        entity_id=entity_id,
        role=role,
        captured_at_s=captured_at,
        confidence=0.9,
        space=SCREEN_SPACE,
        bounds=bounds,
        label=label,
    )


#: Sits under the gaze point (700, 500) used by every routed sample below.
def _save_button():
    return _candidate("save-button", Rect(650, 480, 100, 40), label="Save")


def _grounder(source, **kw):
    kw.setdefault("clock", lambda: NOW)
    return GazeGrounder(source, **kw)


def _targeter(sample, *, grounder=None, focused="editor"):
    desktop = _FakeDesktop(focused, _two_panes())
    return (
        GazeTargeter(
            _SampleBackend(sample), _identity_cal(), desktop, 0.5, grounder=grounder
        ),
        desktop,
    )


# ---- regression guarantee 1: window routing is unchanged --------------------


@pytest.mark.parametrize(
    "candidates",
    [
        pytest.param((), id="unresolved-nothing-there"),
        pytest.param(("one",), id="grounded"),
        pytest.param(("two",), id="ambiguous"),
    ],
)
def test_grounding_never_changes_the_route_decision(candidates):
    """The acceptance criterion as a paired experiment, across all three outcomes."""
    sample = GazeSample(700, 500, confidence=0.9)
    plain, plain_desktop = _targeter(sample)
    bare = plain.retarget()

    entities = {
        (): (),
        ("one",): (_save_button(),),
        ("two",): (_save_button(), _candidate("save-icon", Rect(660, 485, 100, 40))),
    }[candidates]
    grounded, desktop = _targeter(
        GazeSample(700, 500, confidence=0.9), grounder=_grounder(_FakeSource(*entities))
    )
    with_seam = grounded.retarget()

    assert with_seam == bare == RouteDecision(target="browser", used_gaze=True, confident=True)
    assert desktop.activated == plain_desktop.activated == ["browser"]


def test_a_targeter_with_no_grounder_records_no_grounding_at_all():
    targeter, _ = _targeter(GazeSample(700, 500, confidence=0.9))
    targeter.retarget()
    assert targeter.last_grounding is None
    assert targeter.refined_target() == RefinedTarget(window_id="browser")
    assert targeter.refined_target().is_exact is False


# ---- regression guarantee 2: the low-confidence fallback is unchanged -------


def test_low_confidence_gaze_never_reaches_the_semantic_source():
    """Not "asks and ignores the answer" — never asks.

    A sample below `[gaze] confidence_min` falls back to the focused window, and the
    gaze point that produced it is not evidence of anything. Grounding inside the
    *focused* window on the strength of a point the router just refused would invent a
    target out of a rejection.
    """
    source = _FakeSource(_save_button())
    targeter, desktop = _targeter(
        GazeSample(700, 500, confidence=0.2), grounder=_grounder(source)
    )
    decision = targeter.retarget()
    assert decision == RouteDecision(target="editor", used_gaze=False, confident=False)
    assert desktop.activated == []
    assert source.calls == []
    assert targeter.last_grounding is None


def test_a_gaze_point_outside_every_window_still_grounds_nothing():
    source = _FakeSource(_save_button())
    targeter, _ = _targeter(
        GazeSample(9999, 9999, confidence=0.99), grounder=_grounder(source)
    )
    assert targeter.retarget().used_gaze is False
    assert source.calls == []


def test_no_face_at_all_grounds_nothing():
    source = _FakeSource(_save_button())
    targeter, _ = _targeter(None, grounder=_grounder(source))
    assert targeter.retarget().used_gaze is False
    assert source.calls == []


def test_a_grounded_entity_cannot_raise_the_confidence_of_the_gaze_that_found_it():
    """The spec's rule, checked at the number: resolution confidence is the weaker of
    the two observations, so a 0.99-confident accessibility node cannot dress up a
    barely-confident sample."""
    targeter, _ = _targeter(
        GazeSample(700, 500, confidence=0.55),
        grounder=_grounder(_FakeSource(_save_button())),
    )
    targeter.retarget()
    assert targeter.last_grounding.is_grounded
    assert targeter.last_grounding.resolution_confidence == pytest.approx(0.55)


# ---- the feature: one plausible entity refines the target -------------------


def test_one_plausible_entity_refines_the_window_target_to_that_entity():
    source = _FakeSource(_save_button())
    targeter, _ = _targeter(GazeSample(700, 500, confidence=0.9), grounder=_grounder(source))
    targeter.retarget()

    refined = targeter.refined_target()
    assert refined.window_id == "browser"          # unchanged, and it is still first
    assert refined.entity_id == "save-button"
    assert refined.role == "button"
    assert refined.is_exact is True
    assert refined.outcome is GroundingOutcome.GROUNDED


def test_the_source_is_asked_about_the_looked_at_window_as_a_string_and_no_region():
    """`window_id` crosses the Protocol as a string — one adapter must not answer about
    window 7 while another answers about "7" — and the region is None because the only
    honest region is "the window": a radius around a coarse gaze point would be a
    threshold nothing has measured."""
    source = _FakeSource(_save_button())
    targeter, _ = _targeter(GazeSample(700, 500, confidence=0.9), grounder=_grounder(source))
    targeter.retarget()
    assert source.calls == [("browser", None)]


def test_an_integer_window_id_reaches_the_protocol_as_a_string():
    source = _FakeSource()
    desktop = _FakeDesktop(0, [(7, 600, 400, 200, 200)])
    targeter = GazeTargeter(
        _SampleBackend(GazeSample(700, 500, confidence=0.9)),
        _identity_cal(),
        desktop,
        0.5,
        grounder=_grounder(source),
    )
    targeter.retarget()
    assert source.calls == [("7", None)]


def test_the_refined_entity_label_is_not_carried_out_of_the_seam():
    """The candidate's label is user-visible screen text. It has a job inside the
    resolver (an intent hint matches against it) and no business travelling into the
    part a consumer logs."""
    source = _FakeSource(_candidate("subject-field", Rect(650, 480, 100, 40),
                                    role="text", label="Re: salary review"))
    targeter, _ = _targeter(GazeSample(700, 500, confidence=0.9), grounder=_grounder(source))
    targeter.retarget()
    refined = targeter.refined_target()
    assert refined.entity_id == "subject-field" and refined.role == "text"
    assert "salary" not in repr(refined)


# ---- abstention never becomes an exact element ------------------------------


def test_two_indistinguishable_entities_leave_the_target_at_the_window():
    source = _FakeSource(
        _save_button(), _candidate("save-icon", Rect(660, 485, 100, 40))
    )
    targeter, _ = _targeter(GazeSample(700, 500, confidence=0.9), grounder=_grounder(source))
    targeter.retarget()

    assert targeter.last_grounding.outcome is GroundingOutcome.AMBIGUOUS
    refined = targeter.refined_target()
    assert refined.is_exact is False and refined.entity_id is None
    assert refined.window_id == "browser"


def test_an_empty_semantic_tree_leaves_the_target_at_the_window():
    targeter, _ = _targeter(GazeSample(700, 500, confidence=0.9), grounder=_grounder(_FakeSource()))
    targeter.retarget()
    assert targeter.last_grounding.unresolved_reason is UnresolvedReason.SEMANTIC_NO_CANDIDATES
    assert targeter.refined_target().is_exact is False


def test_an_entity_the_user_was_not_looking_at_is_not_grounded():
    """The envelope rule, end to end: a lone candidate elsewhere in the window is still
    not what "this" meant."""
    source = _FakeSource(_candidate("far-button", Rect(510, 10, 60, 30)))
    targeter, _ = _targeter(GazeSample(700, 500, confidence=0.9), grounder=_grounder(source))
    targeter.retarget()
    reason = targeter.last_grounding.unresolved_reason
    assert reason is UnresolvedReason.SEMANTIC_NO_PLAUSIBLE_CANDIDATE
    assert targeter.refined_target().is_exact is False


def test_a_stale_semantic_tree_abstains_rather_than_grounding_where_things_used_to_be():
    source = _FakeSource(_candidate("save-button", Rect(650, 480, 100, 40),
                                    captured_at=NOW - 30.0))
    targeter, _ = _targeter(GazeSample(700, 500, confidence=0.9), grounder=_grounder(source))
    targeter.retarget()
    assert targeter.last_grounding.unresolved_reason is UnresolvedReason.SEMANTIC_ALL_STALE
    assert targeter.refined_target().is_exact is False


def test_a_source_in_another_coordinate_space_abstains():
    """A source publishing candidates in its own pixel grid is a platform bug, not a
    target: the numbers look comparable and are not."""
    other = CoordinateSpace("window-relative")
    source = _FakeSource(
        replace(_save_button(), space=other, bounds=Rect(0, 0, 100, 40))
    )
    targeter, _ = _targeter(GazeSample(700, 500, confidence=0.9), grounder=_grounder(source))
    targeter.retarget()
    assert targeter.last_grounding.unresolved_reason is UnresolvedReason.SEMANTIC_SPACE_MISMATCH


def test_refine_never_promotes_an_alternative_from_an_ambiguous_result():
    """Directly on the pure function, because this is the rule the whole layer exists
    for: an ambiguous result *carries* its candidates, and reading one out of it would
    be the guess ADR-v2-151 forbids."""
    target = TargetSnapshot(
        source=TargetSource.GAZE, timestamp_s=NOW, confidence=0.9,
        space=SCREEN_SPACE, point=Point(700, 500), window_id="browser",
    )
    result = GroundingResult.ambiguous(target, [_save_button(), _candidate("b", Rect(1, 1, 2, 2))])
    refined = refine(RouteDecision("browser", True, True), result)
    assert refined == RefinedTarget(
        window_id="browser", entity_id=None, role=None, outcome=GroundingOutcome.AMBIGUOUS
    )


def test_refine_with_no_decision_and_no_result_is_an_empty_target():
    assert refine(None, None) == RefinedTarget(window_id=None)


# ---- failure isolation ------------------------------------------------------


def test_a_semantic_source_that_raises_leaves_routing_and_dictation_untouched(caplog):
    source = _BoomSource()
    targeter, desktop = _targeter(GazeSample(700, 500, confidence=0.9), grounder=_grounder(source))
    with caplog.at_level("WARNING"):
        decision = targeter.retarget()
    assert decision == RouteDecision(target="browser", used_gaze=True, confident=True)
    assert desktop.activated == ["browser"]        # the burst still lands where it should
    assert targeter.last_grounding is None
    assert targeter.refined_target() == RefinedTarget(window_id="browser")
    assert source.calls == 1
    assert "Semantic grounding failed" in caplog.text


def test_a_failing_source_is_reported_once_per_streak_not_once_per_hold(caplog):
    """ADR-021 in the log: a warning per dictation buries the one line that matters."""
    source = _BoomSource()
    grounder = _grounder(source)
    desktop = _FakeDesktop("editor", _two_panes())
    backend = _SampleBackend(*[GazeSample(700, 500, confidence=0.9)] * 4)
    targeter = GazeTargeter(backend, _identity_cal(), desktop, 0.5, grounder=grounder)
    with caplog.at_level("WARNING"):
        for _ in range(4):
            targeter.retarget()
    assert grounder.failures == 4
    assert caplog.text.count("Semantic grounding failed") == 1


def test_a_source_that_recovers_is_reported_again_when_it_next_fails(caplog):
    """The counterpart: silence must not become permanent, or a second outage after a
    working spell would never be logged."""
    class _FlakySource:
        def __init__(self):
            self.calls = 0

        def snapshot(self, *, window_id, region):
            self.calls += 1
            if self.calls != 2:
                raise RuntimeError("no registry")
            return []

    grounder = _grounder(_FlakySource())
    for _ in range(3):
        with caplog.at_level("WARNING"):
            grounder.ground(window_id="browser", point=(700.0, 500.0), confidence=0.9)
    assert grounder.failures == 2
    assert caplog.text.count("Semantic grounding failed") == 2


def test_a_backend_reporting_an_impossible_confidence_is_isolated_too():
    """The contracts refuse a confidence outside [0, 1] rather than clamping it, so a
    broken backend raises *inside* the seam. It must die there."""
    source = _FakeSource(_save_button())
    grounder = _grounder(source)
    assert grounder.ground(window_id="w", point=(1.0, 2.0), confidence=1.5) is None
    assert grounder.failures == 1
    assert source.calls == []


def test_a_grounder_object_that_is_itself_broken_cannot_break_retargeting():
    """The seam is duck-typed, so the targeter cannot assume it was handed a
    `GazeGrounder`."""
    class _BrokenGrounder:
        def ground(self, **kw):
            raise TypeError("not a grounder")

    targeter, desktop = _targeter(
        GazeSample(700, 500, confidence=0.9), grounder=_BrokenGrounder()
    )
    assert targeter.retarget().target == "browser"
    assert desktop.activated == ["browser"]
    assert targeter.last_grounding is None


def test_a_grounding_answer_never_survives_into_the_next_burst():
    """A stale exact target is worse than none: the second hold found no face, and
    reading the first hold's button would act on a window the user has left."""
    backend = _SampleBackend(GazeSample(700, 500, confidence=0.9), None)
    desktop = _FakeDesktop("editor", _two_panes())
    targeter = GazeTargeter(
        backend, _identity_cal(), desktop, 0.5,
        grounder=_grounder(_FakeSource(_save_button())),
    )
    targeter.retarget()
    assert targeter.refined_target().is_exact is True
    targeter.retarget()
    assert targeter.last_grounding is None
    assert targeter.refined_target().is_exact is False


def test_a_suspended_topology_guard_still_takes_no_sample_and_grounds_nothing():
    """ADR-v2-149's short circuit must keep short-circuiting: a calibration that no
    longer describes the desktop would put the gaze point in the wrong window, and
    asking a semantic source about that window is a wrong target with a precise id."""
    class _Suspended:
        last_check = None

        def suspended(self):
            return True

    source = _FakeSource(_save_button())
    backend = _SampleBackend(GazeSample(700, 500, confidence=0.9))
    desktop = _FakeDesktop("editor", _two_panes())
    targeter = GazeTargeter(
        backend, _identity_cal(), desktop, 0.5,
        topology_guard=_Suspended(), grounder=_grounder(source),
    )
    decision = targeter.retarget()
    assert decision.used_gaze is False and decision.target == "editor"
    assert source.calls == []
    assert targeter.last_grounding is None


# ---- the freshness budget the seam actually enforces ------------------------


def test_a_source_slower_than_the_freshness_budget_makes_its_own_answer_stale():
    """The clock is read twice — once to date the sample, once to judge it — so a slow
    adapter abstains instead of grounding against a screen that has had a second to
    scroll."""
    readings = iter([NOW, NOW + 5.0])
    grounder = GazeGrounder(_FakeSource(_save_button()), clock=lambda: next(readings))
    result = grounder.ground(window_id="browser", point=(700.0, 500.0), confidence=0.9)
    assert result.unresolved_reason is UnresolvedReason.TARGET_STALE


def test_the_injected_policy_is_the_only_place_a_threshold_lives():
    """Nothing in the seam hard-codes a number: a caller that widens the envelope gets
    a candidate the default policy refuses, with no code change here."""
    source = _FakeSource(_candidate("near-miss", Rect(720, 480, 40, 40)))
    strict = _grounder(source)
    assert strict.ground(window_id="w", point=(700.0, 500.0), confidence=0.9).outcome is (
        GroundingOutcome.UNRESOLVED
    )
    lenient = _grounder(
        source, resolver=TargetResolver(ResolutionPolicy(envelope_expansion_px=50.0))
    )
    assert lenient.ground(window_id="w", point=(700.0, 500.0), confidence=0.9).is_grounded


def test_an_intent_hint_reaches_the_resolver_and_only_filters():
    """The hint is carried through the seam unchanged, which means it keeps the
    resolver's one-directional rule: it can drop a plausible candidate and can never
    add an implausible one."""
    source = _FakeSource(
        _save_button(), _candidate("save-icon", Rect(660, 485, 100, 40), role="image")
    )
    grounder = _grounder(source)
    hinted = grounder.ground(
        window_id="browser", point=(700.0, 500.0), confidence=0.9,
        hint=IntentHint(verb="click", role="button"),
    )
    assert hinted.is_grounded and hinted.candidate.entity_id == "save-button"
    assert grounder.ground(
        window_id="browser", point=(700.0, 500.0), confidence=0.9,
        hint=IntentHint(verb="click", role="menu"),
    ).outcome is GroundingOutcome.UNRESOLVED


# ---- regression guarantee 3: window deixis is unchanged ---------------------


def _daemon(**gaze) -> Daemon:
    from yazses.platform import get_platform

    cfg = replace(Config(), gaze=replace(GazeConfig(), **gaze))
    return Daemon(config=cfg, platform=get_platform())


def _grounded_targeter():
    """A real targeter that has just grounded a real entity inside the browser."""
    targeter, desktop = _targeter(
        GazeSample(700, 500, confidence=0.9), grounder=_grounder(_FakeSource(_save_button()))
    )
    targeter.retarget()
    assert targeter.refined_target().is_exact, "fixture must actually ground something"
    desktop.activated.clear()
    return targeter, desktop


def test_deixis_acts_on_the_window_even_when_an_exact_entity_was_grounded():
    daemon = _daemon(enabled=True, deixis=True)
    targeter, desktop = _grounded_targeter()
    daemon._gaze_targeter = targeter
    assert daemon._try_deixis("focus this", {})
    assert desktop.activated == ["browser"]        # the window, not "save-button"


def test_the_destructive_confirm_gate_is_unmoved_by_a_grounded_entity(mocker):
    """"close this" on a gaze-routed target still asks first. An exact element id is a
    better *answer*, not a reason to lower a guard that exists because the sensor is
    coarse — and grounding says nothing about whether an action is safe."""
    notify = mocker.patch("yazses.system.notify.notify")
    daemon = _daemon(enabled=True, deixis=True)
    targeter, desktop = _grounded_targeter()
    daemon._gaze_targeter = targeter
    assert daemon._try_deixis("close this", {})
    assert desktop.closed == [] and notify.called


def test_deixis_ignores_grounding_when_the_route_fell_back_to_focus():
    daemon = _daemon(enabled=True, deixis=True)
    targeter, desktop = _targeter(
        GazeSample(700, 500, confidence=0.2), grounder=_grounder(_FakeSource(_save_button()))
    )
    targeter.retarget()
    daemon._gaze_targeter = targeter
    assert daemon._try_deixis("close this", {})
    assert desktop.closed == ["editor"]            # focus fallback: no confirm, as before


def test_a_failing_semantic_source_does_not_break_an_ordinary_dictation_hold(caplog):
    """The daemon's own entry point. `_on_hold_start` wraps `retarget` in a warning, so
    the proof is that the warning never fires: the failure was already isolated one
    layer down, and the burst went on to focus the window it should have."""
    daemon = _daemon(enabled=True, route_dictation=True, deixis=True)
    targeter, desktop = _targeter(
        GazeSample(700, 500, confidence=0.9), grounder=_grounder(_BoomSource())
    )
    daemon._gaze_targeter = targeter
    with caplog.at_level("WARNING"):
        daemon._on_hold_start(0)
    assert desktop.activated == ["browser"]
    assert "Gaze retarget failed" not in caplog.text
    assert targeter.last_decision.used_gaze is True


# ---- no new dependency path -------------------------------------------------


def test_the_seam_imports_nothing_beyond_the_standard_library_and_yazses():
    """"No new screen capture, network or dependency path" is checkable, so it is
    checked here rather than promised in a docstring. `tests/test_egress_inventory.py`
    owns the network half for the whole tree; this is the import half for the one
    module that would be tempted — a platform accessibility binding belongs behind the
    Protocol, never inside a gaze module."""
    path = Path(GazeGrounder.__module__.replace(".", "/") + ".py")
    source = (Path(__file__).resolve().parent.parent / "src" / path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
    assert roots <= set(sys.stdlib_module_names) | {"yazses"}, roots
    # Named rather than left implicit: these are the four bindings an adapter would
    # reach for, and "it is not in the standard library" is a weaker sentence than
    # "it is not this one". Matched against the import roots, not the file text — the
    # module docstring says all four words while explaining why none of them is here.
    banned = {"pyatspi", "AppKit", "Quartz", "uiautomation", "comtypes", "mss"}
    assert not (roots & banned)
