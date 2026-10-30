"""``yazses.xr.grounded`` — XR panel hits as grounding targets, end to end."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from yazses.grounding import (
    CoordinateSpace,
    GroundingOutcome,
    Point,
    Rect,
    SemanticCandidate,
    SemanticSourceKind,
    TargetResolver,
    TargetSnapshot,
    TargetSource,
    UnresolvedReason,
)
from yazses.xr.grounded import panel_space, snapshot_series, to_target_snapshot
from yazses.xr.types import Panel, PanelHit, Ray, RaySource, Vec3, XrSample

SPACE = panel_space("p1")


def _sample(t: float = 10.0, confidence: float = 0.9) -> XrSample:
    return XrSample(t, RaySource.HAND, Ray(Vec3(0, 0, 0), Vec3(0, 0, -1)), confidence)


def _panel(panel_id: str = "p1") -> Panel:
    return Panel(panel_id, Vec3(0, 0, -2), Vec3(0, 0, 1), Vec3(0, 1, 0), 1.0, 1.0)


def _candidate(bounds: Rect, *, entity_id: str = "btn", t: float = 10.0) -> SemanticCandidate:
    return SemanticCandidate(
        source=SemanticSourceKind.ACCESSIBILITY,
        entity_id=entity_id,
        role="button",
        captured_at_s=t,
        confidence=0.9,
        space=SPACE,
        bounds=bounds,
    )


# ---- panel_space ---------------------------------------------------------------
def test_panel_space_names_and_versions() -> None:
    assert panel_space("abc") == CoordinateSpace("xr-panel:abc", 0)
    assert panel_space("abc", 3) == CoordinateSpace("xr-panel:abc", 3)
    # A moved panel (new version) is a different space, so old snapshots cannot match.
    assert panel_space("abc", 1) != panel_space("abc", 2)


def test_panel_space_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        panel_space("")
    with pytest.raises(ValueError):
        panel_space("abc", -1)


# ---- to_target_snapshot --------------------------------------------------------
def test_hit_maps_to_flipped_point_in_named_space() -> None:
    snap = to_target_snapshot(_sample(), PanelHit("p1", 0.25, 0.75, 2.0), _panel(), space=SPACE)
    assert snap.source is TargetSource.XR_RAY
    assert snap.space == SPACE
    assert snap.point == Point(0.25, 0.25)  # v=1 is the top, so y = 1 - v
    assert snap.bounds is None
    assert snap.timestamp_s == 10.0


@pytest.mark.parametrize(
    ("u", "v", "expected"),
    [(0.0, 1.0, (0.0, 0.0)), (1.0, 0.0, (1.0, 1.0)), (0.5, 0.5, (0.5, 0.5))],
)
def test_corners_and_centre(u: float, v: float, expected: tuple[float, float]) -> None:
    snap = to_target_snapshot(_sample(), PanelHit("p1", u, v, 1.0), None, space=SPACE)
    assert snap.point == Point(*expected)


def test_no_hit_is_geometry_less_confidence_only() -> None:
    snap = to_target_snapshot(_sample(confidence=0.7), None, _panel(), space=SPACE)
    assert not snap.has_geometry
    assert snap.space is None and snap.window_id is None
    assert snap.confidence == 0.7
    assert snap.source is TargetSource.XR_RAY


def test_window_comes_from_the_mapping_only() -> None:
    hit = PanelHit("p1", 0.5, 0.5, 1.0)
    mapped = to_target_snapshot(
        _sample(), hit, _panel(), space=SPACE, window_for_panel={"p1": "0x42", "p2": "0x43"}
    )
    assert mapped.window_id == "0x42"
    other = to_target_snapshot(_sample(), hit, _panel(), space=SPACE, window_for_panel={"p2": "x"})
    assert other.window_id is None
    assert to_target_snapshot(_sample(), hit, None, space=SPACE).window_id is None
    # A blank entry means "unmapped", not a crash and not a window called "".
    blank = to_target_snapshot(_sample(), hit, None, space=SPACE, window_for_panel={"p1": ""})
    assert blank.window_id is None


def test_no_hit_ignores_window_mapping() -> None:
    snap = to_target_snapshot(_sample(), None, _panel(), space=SPACE, window_for_panel={"p1": "w"})
    assert snap.window_id is None


def test_mismatched_panel_is_refused() -> None:
    with pytest.raises(ValueError, match="p1"):
        to_target_snapshot(_sample(), PanelHit("p1", 0.5, 0.5, 1.0), _panel("p2"), space=SPACE)


@pytest.mark.parametrize("confidence", [0.0, 0.3, 0.5, 0.999, 1.0])
def test_confidence_is_the_samples_exactly(confidence: float) -> None:
    hit = PanelHit("p1", 0.5, 0.5, 1.0)
    assert to_target_snapshot(_sample(confidence=confidence), hit, None, space=SPACE).confidence == confidence
    assert to_target_snapshot(_sample(confidence=confidence), None, None, space=SPACE).confidence == confidence


def test_zero_confidence_hit_still_builds() -> None:
    snap = to_target_snapshot(_sample(confidence=0.0), PanelHit("p1", 0.1, 0.1, 0.0), None, space=SPACE)
    assert snap.confidence == 0.0 and snap.has_geometry


# ---- snapshot_series -----------------------------------------------------------
def test_series_aligns_and_preserves_order() -> None:
    samples = [_sample(1.0, 0.9), _sample(2.0, 0.6), _sample(3.0, 0.8)]
    hits = [PanelHit("p1", 0.1, 0.9, 1.0), None, PanelHit("p2", 0.2, 0.2, 1.0)]
    out = snapshot_series(
        samples, hits, {"p1": _panel("p1")}, window_for_panel={"p2": "w2"}
    )
    assert [s.timestamp_s for s in out] == [1.0, 2.0, 3.0]
    assert out[0].space == panel_space("p1")
    assert out[0].point is not None
    assert (out[0].point.x, out[0].point.y) == (0.1, pytest.approx(0.1))
    assert not out[1].has_geometry
    assert out[2].space == panel_space("p2") and out[2].window_id == "w2"
    assert [s.confidence for s in out] == [0.9, 0.6, 0.8]


def test_series_explicit_space_wins() -> None:
    out = snapshot_series([_sample()], [PanelHit("p1", 0.5, 0.5, 1.0)], space=panel_space("p1", 4))
    assert out[0].space == CoordinateSpace("xr-panel:p1", 4)


def test_series_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        snapshot_series([_sample(), _sample()], [None])
    with pytest.raises(ValueError):
        snapshot_series([], [None])


def test_series_empty_and_checks_panel_identity() -> None:
    assert snapshot_series([], []) == ()
    with pytest.raises(ValueError):
        snapshot_series([_sample()], [PanelHit("p1", 0.5, 0.5, 1.0)], {"p1": _panel("p2")})


# ---- the real resolver ---------------------------------------------------------
def test_snapshot_feeds_real_resolver_and_grounds() -> None:
    # The hit is the upper-left of the panel: v=0.9 -> y=0.1.
    snap = to_target_snapshot(_sample(), PanelHit("p1", 0.1, 0.9, 1.0), _panel(), space=SPACE)
    top_left = _candidate(Rect(0.0, 0.0, 0.5, 0.5), entity_id="tl")
    bottom_right = _candidate(Rect(0.5, 0.5, 0.5, 0.5), entity_id="br")
    result = TargetResolver().resolve(snap, [bottom_right, top_left], now_s=10.0)
    assert result.outcome is GroundingOutcome.GROUNDED
    assert result.candidate is not None and result.candidate.entity_id == "tl"
    # Semantics never lift the sample's confidence.
    assert result.resolution_confidence <= 0.9


def test_y_flip_decides_which_control_is_hit() -> None:
    # Same u, opposite v: only the flip keeps these on different candidates.
    top = _candidate(Rect(0.0, 0.0, 1.0, 0.5), entity_id="top")
    bottom = _candidate(Rect(0.0, 0.5, 1.0, 0.5), entity_id="bottom")
    resolver = TargetResolver()
    for v, want in ((0.9, "top"), (0.1, "bottom")):
        snap = to_target_snapshot(_sample(), PanelHit("p1", 0.5, v, 1.0), None, space=SPACE)
        res = resolver.resolve(snap, [top, bottom], now_s=10.0)
        assert res.candidate is not None and res.candidate.entity_id == want


def test_no_hit_yields_unresolved_through_real_resolver() -> None:
    snap = to_target_snapshot(_sample(), None, _panel(), space=SPACE)
    res = TargetResolver().resolve(snap, [_candidate(Rect(0, 0, 1, 1))], now_s=10.0)
    assert res.outcome is GroundingOutcome.UNRESOLVED
    assert res.unresolved_reason is UnresolvedReason.TARGET_GEOMETRY_MISSING


def test_low_confidence_sample_is_refused_by_resolver() -> None:
    snap = to_target_snapshot(
        _sample(confidence=0.2), PanelHit("p1", 0.5, 0.5, 1.0), None, space=SPACE
    )
    res = TargetResolver().resolve(snap, [_candidate(Rect(0, 0, 1, 1))], now_s=10.0)
    assert res.unresolved_reason is UnresolvedReason.TARGET_CONFIDENCE_BELOW_FLOOR


def test_moved_panel_candidate_in_other_space_mismatches() -> None:
    snap = to_target_snapshot(
        _sample(), PanelHit("p1", 0.5, 0.5, 1.0), None, space=panel_space("p1", 1)
    )
    res = TargetResolver().resolve(snap, [_candidate(Rect(0, 0, 1, 1))], now_s=10.0)
    assert res.outcome is GroundingOutcome.UNRESOLVED
    assert res.unresolved_reason is UnresolvedReason.SEMANTIC_SPACE_MISMATCH


# ---- property: every output is a valid TargetSnapshot -------------------------
unit = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


@given(
    t=st.floats(min_value=0.0, max_value=1e9, allow_nan=False),
    confidence=unit,
    u=unit,
    v=unit,
    dist=st.floats(min_value=0.0, max_value=1e3, allow_nan=False),
    has_hit=st.booleans(),
    mapped=st.booleans(),
)
def test_every_output_is_a_valid_snapshot(
    t: float, confidence: float, u: float, v: float, dist: float, has_hit: bool, mapped: bool
) -> None:
    hit = PanelHit("p1", u, v, dist) if has_hit else None
    snap = to_target_snapshot(
        _sample(t, confidence),
        hit,
        _panel(),
        space=SPACE,
        window_for_panel={"p1": "w"} if mapped else None,
    )
    assert isinstance(snap, TargetSnapshot)
    assert snap.confidence == confidence  # never inflated, never altered
    assert snap.timestamp_s == t
    assert snap.has_geometry == has_hit
    if snap.point is not None:
        assert 0.0 <= snap.point.x <= 1.0 and 0.0 <= snap.point.y <= 1.0
        assert snap.space == SPACE
    else:
        assert snap.space is None and snap.window_id is None
    # And the real resolver never raises on it.
    res = TargetResolver().resolve(snap, [_candidate(Rect(0, 0, 1, 1), t=t)], now_s=t)
    assert res.target is snap


# --- regressions: explicit space vs. panels, panel versions ---------------------------


def _hit(panel_id: str) -> PanelHit:
    return PanelHit(panel_id, 0.5, 0.5, 2.0)


def test_explicit_space_over_hits_on_two_panels_is_refused() -> None:
    # Reproducer: both snapshots used to come back labelled 'xr-panel:a'.
    with pytest.raises(ValueError, match="one panel"):
        snapshot_series(
            [_sample(1.0), _sample(2.0)],
            [_hit("a"), _hit("b")],
            space=panel_space("a"),
        )


def test_explicit_space_over_one_panel_is_accepted() -> None:
    sp = panel_space("a", 3)
    snaps = snapshot_series(
        [_sample(1.0), _sample(2.0), _sample(3.0)], [_hit("a"), None, _hit("a")], space=sp
    )
    assert [s.space for s in snaps] == [sp, None, sp]


def test_default_spaces_are_per_panel_and_versioned() -> None:
    snaps = snapshot_series(
        [_sample(1.0), _sample(2.0)],
        [_hit("a"), _hit("b")],
        versions={"a": 4},
    )
    assert snaps[0].space == panel_space("a", 4)
    assert snaps[1].space == panel_space("b", 0)


def test_a_moved_panel_invalidates_older_snapshots() -> None:
    before = snapshot_series([_sample()], [_hit("a")], versions={"a": 1})[0]
    after = snapshot_series([_sample()], [_hit("a")], versions={"a": 2})[0]
    assert before.space != after.space
    # Without versions the version is always 0, so a move would invalidate nothing.
    plain = snapshot_series([_sample()], [_hit("a")])[0]
    assert plain.space == panel_space("a", 0)


def test_space_and_versions_together_are_refused() -> None:
    with pytest.raises(ValueError, match="either"):
        snapshot_series([_sample()], [_hit("a")], space=panel_space("a"), versions={"a": 1})
