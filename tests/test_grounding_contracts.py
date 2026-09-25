"""The grounding vocabulary is a value layer, and the tests hold it to that.

`src/yazses/grounding/contracts.py` is phase P0 of ADR-v2-151: the immutable types a
coarse target, a semantic UI candidate and a tri-state grounding result are expressed
in. Three properties have to hold or the rest of the programme inherits a defect:

1. **Value semantics.** These objects are compared, hashed, put in sets and replayed
   by a fixture harness (#445). A mutable or identity-compared "value" would make a
   replay test pass for the wrong reason.
2. **Bad input fails at the seam.** A NaN confidence, a NaN timestamp or a negative
   rectangle all compare False against every threshold rather than raising, so a
   resolver written against them abstains "correctly" and nobody ever learns the
   adapter is broken. Construction refuses them instead.
3. **The layer stays pure.** The ADR forbids a live platform object, a camera frame
   or a screenshot in these values, and forbids the module importing pyatspi, PyObjC,
   a Win32 binding, OpenCV or MediaPipe. That is checked mechanically below, because
   "we will notice in review" is exactly how the first accessibility node gets stored.

The resolver itself is #442 and is deliberately not exercised here.
"""

from __future__ import annotations

import ast
import dataclasses
import math
import re
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import yazses.grounding.contracts as contracts
from yazses.grounding import (
    CoordinateSpace,
    GroundingEvidence,
    GroundingOutcome,
    GroundingResult,
    Point,
    Rect,
    SemanticCandidate,
    SemanticSource,
    SemanticSourceKind,
    TargetSnapshot,
    TargetSource,
)

SPACE = CoordinateSpace("screen", 1)


def a_target(**kw) -> TargetSnapshot:
    """A plausible gaze snapshot; keyword args override one field at a time."""
    base = dict(
        source=TargetSource.GAZE,
        timestamp_s=1234.5,
        confidence=0.8,
        space=SPACE,
        point=Point(100.0, 200.0),
        window_id="win-1",
    )
    base.update(kw)
    return TargetSnapshot(**base)  # type: ignore[arg-type]


def a_candidate(**kw) -> SemanticCandidate:
    base = dict(
        source=SemanticSourceKind.ACCESSIBILITY,
        entity_id="node-7",
        role="button",
        captured_at_s=1234.4,
        confidence=0.9,
        space=SPACE,
        bounds=Rect(90.0, 190.0, 40.0, 20.0),
        label="Save",
        actions=("press",),
    )
    base.update(kw)
    return SemanticCandidate(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 1. Value semantics
# --------------------------------------------------------------------------- #
def test_equal_fields_mean_equal_values() -> None:
    assert a_target() == a_target()
    assert a_candidate() == a_candidate()
    assert GroundingResult.unresolved(a_target()) == GroundingResult.unresolved(a_target())


def test_one_different_field_means_a_different_value() -> None:
    assert a_target(confidence=0.81) != a_target()
    assert a_candidate(entity_id="node-8") != a_candidate()
    assert Rect(0, 0, 10, 10) != Rect(0, 0, 10, 11)
    # The whole point of CoordinateSpace.version: a re-calibration makes old
    # geometry compare unequal instead of silently grounding against a dead layout.
    assert CoordinateSpace("screen", 1) != CoordinateSpace("screen", 2)


def test_values_are_hashable_and_deduplicate() -> None:
    assert len({a_candidate(), a_candidate(), a_candidate(entity_id="other")}) == 2
    assert len({Point(1.0, 2.0), Point(1.0, 2.0)}) == 1


def test_values_are_frozen() -> None:
    for value in (a_target(), a_candidate(), Rect(0, 0, 1, 1), SPACE):
        with pytest.raises(FrozenInstanceError):
            value.confidence = 0.1  # type: ignore[misc]


def test_replace_produces_a_new_validated_value() -> None:
    """dataclasses.replace must not bypass validation — it re-runs __post_init__."""
    original = a_candidate()
    assert dataclasses.replace(original, confidence=0.1).confidence == 0.1
    assert original.confidence == 0.9
    with pytest.raises(ValueError):
        dataclasses.replace(original, confidence=1.5)


# --------------------------------------------------------------------------- #
# 2. Invalid confidence / time / geometry
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [-0.01, 1.01, float("nan"), float("inf"), -float("inf")])
def test_confidence_outside_the_unit_interval_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="0.0, 1.0"):
        a_target(confidence=bad)
    with pytest.raises(ValueError, match="0.0, 1.0"):
        a_candidate(confidence=bad)
    with pytest.raises(ValueError, match="0.0, 1.0"):
        GroundingResult.grounded(a_target(), a_candidate(), resolution_confidence=bad)


def test_confidence_is_refused_not_clamped() -> None:
    """A clamp would let a broken adapter announce certainty and be believed."""
    with pytest.raises(ValueError):
        a_target(confidence=1e9)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_timestamps_are_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="monotonic timestamp"):
        a_target(timestamp_s=bad)
    with pytest.raises(ValueError, match="monotonic timestamp"):
        a_candidate(captured_at_s=bad)


def test_a_negative_monotonic_reading_is_accepted() -> None:
    """CPython leaves time.monotonic()'s reference point undefined, so a negative
    reading is not provably impossible; only non-finite values break freshness
    arithmetic. This records the choice so a later 'tidy-up' does not reverse it."""
    assert a_target(timestamp_s=-5.0).timestamp_s == -5.0


@pytest.mark.parametrize("bad", [(-1.0, 10.0), (10.0, -1.0)])
def test_a_negative_sized_rectangle_is_refused(bad: tuple[float, float]) -> None:
    width, height = bad
    with pytest.raises(ValueError, match="non-negative"):
        Rect(0.0, 0.0, width, height)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_geometry_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        Rect(bad, 0.0, 1.0, 1.0)
    with pytest.raises(ValueError, match="finite"):
        Point(0.0, bad)


def test_geometry_without_a_coordinate_space_is_refused() -> None:
    """A point with no declared space is a number that looks comparable and is not —
    the spec's step-1 coordinate-space rejection has nothing to reject without it."""
    with pytest.raises(ValueError, match="coordinate space"):
        a_target(space=None)
    with pytest.raises(ValueError, match="coordinate space"):
        a_target(space=None, point=None, bounds=Rect(0, 0, 10, 10))
    with pytest.raises(ValueError, match="coordinate space"):
        a_candidate(space=None)


def test_a_snapshot_with_no_geometry_at_all_is_valid() -> None:
    """A webcam frame with no face is a real observation: low confidence, nothing
    else. It is the resolver's UNRESOLVED input, not a construction error."""
    blind = TargetSnapshot(source=TargetSource.GAZE, timestamp_s=1.0, confidence=0.0)
    assert blind.has_geometry is False
    assert a_target().has_geometry is True


def test_empty_identifiers_are_refused() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        a_candidate(entity_id="")
    with pytest.raises(ValueError, match="must not be empty"):
        a_candidate(role="")
    with pytest.raises(ValueError, match="must not be empty"):
        a_target(window_id="")
    with pytest.raises(ValueError, match="must not be empty"):
        CoordinateSpace("")
    with pytest.raises(ValueError, match=">= 0"):
        CoordinateSpace("screen", -1)


# --------------------------------------------------------------------------- #
# Rect geometry helpers (used by the resolver in #442; the arithmetic lives here
# so two implementations of "inside" cannot drift apart).
# --------------------------------------------------------------------------- #
def test_containment_is_half_open_so_neighbours_do_not_both_claim_an_edge() -> None:
    left = Rect(0.0, 0.0, 10.0, 10.0)
    right = Rect(10.0, 0.0, 10.0, 10.0)
    edge = Point(10.0, 5.0)
    assert left.contains(edge) is False
    assert right.contains(edge) is True
    assert left.contains(Point(0.0, 0.0)) is True
    assert left.contains(Point(-0.1, 5.0)) is False


def test_a_zero_size_rectangle_contains_and_intersects_nothing() -> None:
    """Including when it sits *inside* the other rectangle — the pairwise overlap
    formula reports that as an intersection, and an area-less candidate would then
    pass the spatial envelope."""
    empty = Rect(5.0, 5.0, 0.0, 0.0)
    around = Rect(0.0, 0.0, 10.0, 10.0)
    assert empty.contains(Point(5.0, 5.0)) is False
    assert empty.intersects(around) is False
    assert around.intersects(empty) is False
    assert Rect(5.0, 5.0, 0.0, 10.0).intersects(around) is False


def test_intersection_is_symmetric_and_excludes_touching_edges() -> None:
    a = Rect(0.0, 0.0, 10.0, 10.0)
    overlapping = Rect(5.0, 5.0, 10.0, 10.0)
    touching = Rect(10.0, 0.0, 10.0, 10.0)
    assert a.intersects(overlapping) and overlapping.intersects(a)
    assert not a.intersects(touching) and not touching.intersects(a)


def test_center_is_the_midpoint() -> None:
    assert Rect(10.0, 20.0, 4.0, 6.0).center == Point(12.0, 23.0)


# --------------------------------------------------------------------------- #
# 3. All three result states, and the invariants that keep them distinct
# --------------------------------------------------------------------------- #
def test_grounded_carries_one_candidate_with_its_evidence() -> None:
    result = GroundingResult.grounded(
        a_target(),
        a_candidate(),
        resolution_confidence=0.72,
        evidence=[GroundingEvidence.INSIDE_TARGET_REGION, GroundingEvidence.ROLE_MATCH],
        alternatives=[a_candidate(entity_id="node-8")],
    )
    assert result.outcome is GroundingOutcome.GROUNDED
    assert result.is_grounded is True
    assert result.candidate is not None and result.candidate.entity_id == "node-7"
    assert result.resolution_confidence == 0.72
    assert result.evidence == (
        GroundingEvidence.INSIDE_TARGET_REGION,
        GroundingEvidence.ROLE_MATCH,
    )
    # Provenance survives the result: the ADR forbids collapsing "which source said
    # so" into the single confidence float.
    assert result.candidate.source is SemanticSourceKind.ACCESSIBILITY


def test_sequences_are_normalised_to_tuples_so_the_result_stays_immutable() -> None:
    evidence = [GroundingEvidence.WINDOW_MATCH]
    result = GroundingResult.grounded(
        a_target(), a_candidate(), resolution_confidence=0.5, evidence=evidence
    )
    evidence.append(GroundingEvidence.ROLE_MATCH)
    assert result.evidence == (GroundingEvidence.WINDOW_MATCH,)
    assert isinstance(result.alternatives, tuple)


def test_a_list_passed_straight_to_the_constructor_is_frozen_too() -> None:
    """frozen=True blocks later mutation, not a list handed in at construction — and
    one list makes the whole value unhashable, which the replay harness relies on."""
    direct = GroundingResult(
        outcome=GroundingOutcome.GROUNDED,
        target=a_target(),
        candidate=a_candidate(),
        alternatives=[a_candidate(entity_id="node-8")],  # type: ignore[arg-type]
        evidence=[GroundingEvidence.ROLE_MATCH],  # type: ignore[arg-type]
    )
    assert isinstance(direct.alternatives, tuple)
    assert isinstance(direct.evidence, tuple)
    assert len({direct, direct}) == 1  # hashable; `assert hash(x)` flakes when it is 0
    assert isinstance(a_candidate(actions=["press", "focus"]).actions, tuple)
    assert len({a_candidate(actions=["press"])}) == 1


def test_ambiguous_keeps_every_plausible_candidate_and_no_confidence() -> None:
    candidates = [a_candidate(), a_candidate(entity_id="node-8")]
    result = GroundingResult.ambiguous(
        a_target(), candidates, evidence=[GroundingEvidence.INSIDE_TARGET_REGION]
    )
    assert result.outcome is GroundingOutcome.AMBIGUOUS
    assert result.is_grounded is False
    assert result.candidate is None
    assert len(result.alternatives) == 2
    assert result.resolution_confidence == 0.0


def test_unresolved_carries_nothing_but_the_target() -> None:
    result = GroundingResult.unresolved(a_target())
    assert result.outcome is GroundingOutcome.UNRESOLVED
    assert result.is_grounded is False
    assert result.candidate is None
    assert result.alternatives == ()
    assert result.evidence == ()
    assert result.resolution_confidence == 0.0


def test_every_outcome_is_constructible_and_distinguishable() -> None:
    """All three states exist and no two are confusable — the acceptance criterion."""
    results = {
        GroundingResult.grounded(a_target(), a_candidate(), resolution_confidence=0.5),
        GroundingResult.ambiguous(a_target(), [a_candidate(), a_candidate(entity_id="b")]),
        GroundingResult.unresolved(a_target()),
    }
    assert {r.outcome for r in results} == set(GroundingOutcome)
    assert len(results) == 3


def test_a_grounded_result_must_name_its_candidate() -> None:
    with pytest.raises(ValueError, match="must name the candidate"):
        GroundingResult(outcome=GroundingOutcome.GROUNDED, target=a_target())


def test_an_abstaining_result_may_not_name_a_candidate() -> None:
    """Otherwise a caller reads `.candidate` without checking `.outcome` and acts on
    something the resolver deliberately refused to choose."""
    for outcome in (GroundingOutcome.AMBIGUOUS, GroundingOutcome.UNRESOLVED):
        with pytest.raises(ValueError, match="must not name a candidate"):
            GroundingResult(outcome=outcome, target=a_target(), candidate=a_candidate())


def test_an_abstaining_result_may_not_carry_confidence() -> None:
    with pytest.raises(ValueError, match="0.0 confidence"):
        GroundingResult(
            outcome=GroundingOutcome.AMBIGUOUS,
            target=a_target(),
            alternatives=(a_candidate(), a_candidate(entity_id="b")),
            resolution_confidence=0.9,
        )


def test_one_candidate_is_an_answer_not_an_ambiguity() -> None:
    with pytest.raises(ValueError, match="at least two"):
        GroundingResult.ambiguous(a_target(), [a_candidate()])
    with pytest.raises(ValueError, match="at least two"):
        GroundingResult.ambiguous(a_target(), [])


def test_unresolved_may_not_smuggle_candidates_or_evidence() -> None:
    with pytest.raises(ValueError, match="no candidates and no evidence"):
        GroundingResult(
            outcome=GroundingOutcome.UNRESOLVED,
            target=a_target(),
            alternatives=(a_candidate(),),
        )
    with pytest.raises(ValueError, match="no candidates and no evidence"):
        GroundingResult(
            outcome=GroundingOutcome.UNRESOLVED,
            target=a_target(),
            evidence=(GroundingEvidence.WINDOW_MATCH,),
        )


# --------------------------------------------------------------------------- #
# The SemanticSource protocol: read-only, and satisfiable without a desktop
# --------------------------------------------------------------------------- #
class _FakeSource:
    def snapshot(self, *, window_id: str | None, region: Rect | None):
        return [a_candidate()]


class _NotASource:
    def read(self):  # pragma: no cover - never called
        return []


def test_a_plain_object_satisfies_the_semantic_source_protocol() -> None:
    """CI has no AT-SPI bus, no macOS Accessibility and no UI Automation. If a list
    of values could not stand in for a source, none of #442-#445 would be testable."""
    assert isinstance(_FakeSource(), SemanticSource)
    assert not isinstance(_NotASource(), SemanticSource)
    assert list(_FakeSource().snapshot(window_id="win-1", region=None)) == [a_candidate()]


def test_the_protocol_exposes_no_way_to_act() -> None:
    """Grounding answers what "this" refers to. Clicking, focusing and typing stay
    downstream of the safety layer (ADR-v2-151, ADR-021)."""
    methods = {name for name in dir(SemanticSource) if not name.startswith("_")}
    assert methods == {"snapshot"}


# --------------------------------------------------------------------------- #
# The purity guards. These are the ones that stop the layer rotting.
# --------------------------------------------------------------------------- #
CONTRACTS_PATH = Path(contracts.__file__)

#: Everything the vocabulary is allowed to import. stdlib, and not even all of it:
#: no `time` (the caller supplies timestamps, so tests stay deterministic), no `os`,
#: no `socket`, no `pathlib`.
ALLOWED_IMPORTS = {"__future__", "collections", "dataclasses", "enum", "math", "typing"}

FORBIDDEN_IMPORTS = {
    "cv2", "mediapipe", "pyatspi", "gi", "objc", "AppKit", "Quartz",
    "ApplicationServices", "win32api", "win32gui", "comtypes", "uiautomation",
    "numpy", "PIL", "mss", "requests", "urllib", "socket", "http",
}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise AssertionError("the contracts module must not import relatively")
            roots.add((node.module or "").split(".")[0])
    return roots


def test_the_import_scan_actually_reads_the_module() -> None:
    """Guard the guard: a wrong path or a silent parse failure would report an empty
    import set and every purity assertion below would pass on nothing."""
    roots = _imported_roots(CONTRACTS_PATH)
    assert CONTRACTS_PATH.name == "contracts.py"
    assert len(roots) >= 4, f"only found {roots!r} — the scan is not reading the module"
    assert "math" in roots


def test_the_vocabulary_imports_nothing_but_a_short_stdlib_list() -> None:
    unexpected = _imported_roots(CONTRACTS_PATH) - ALLOWED_IMPORTS
    assert not unexpected, (
        f"{CONTRACTS_PATH.name} imports {sorted(unexpected)}. This layer is the one "
        "thing in the grounding package that every other phase depends on; it stays "
        "a leaf so it can be imported on a machine with no desktop session at all."
    )
    assert not _imported_roots(CONTRACTS_PATH) & FORBIDDEN_IMPORTS
    assert "yazses" not in _imported_roots(CONTRACTS_PATH)


def _value_types() -> list[type]:
    return [
        obj
        for obj in vars(contracts).values()
        if isinstance(obj, type) and dataclasses.is_dataclass(obj)
    ]


#: Field-name words that would mean a live object or raw pixels had been stored.
#: Matched as whole underscore-separated words, not substrings: the first draft of
#: this guard used substrings and flagged `alternatives` (which contains "native")
#: and `captured_at_s` (a timestamp), which is how a guard teaches people to widen
#: its allow-list until it catches nothing.
FORBIDDEN_FIELD_WORDS = frozenset({
    "frame", "frames", "image", "screenshot", "pixmap", "pixels", "surface",
    "bitmap", "handle", "native", "raw", "ndarray", "accessible", "node",
    "element", "obj", "ptr", "ref",
})


def _offending_field_names(names) -> list[str]:
    return [
        name
        for name in names
        if FORBIDDEN_FIELD_WORDS & set(name.lower().split("_"))
    ]


def test_the_field_name_guard_catches_what_it_claims_to() -> None:
    """A name check that flags nothing is indistinguishable from a passing suite."""
    assert _offending_field_names(["frame", "native_handle", "raw_pixels"]) == [
        "frame", "native_handle", "raw_pixels",
    ]
    assert _offending_field_names(["captured_at_s", "alternatives", "entity_id"]) == []

#: Every type name a field annotation may be built from: the module's own value
#: types plus primitives. Anything else is either a platform object or a mutable
#: container that would break value semantics.
ALLOWED_ANNOTATION_NAMES = {
    "str", "int", "float", "bool", "tuple", "None",
    "CoordinateSpace", "Point", "Rect", "TargetSource", "TargetSnapshot",
    "SemanticSourceKind", "SemanticCandidate", "GroundingEvidence", "GroundingOutcome",
    "GroundingResult",
}


def test_the_dataclass_scan_finds_every_value_type() -> None:
    """Guard the guard again: an empty list makes the next two tests vacuous."""
    names = {cls.__name__ for cls in _value_types()}
    assert {
        "CoordinateSpace", "Point", "Rect",
        "TargetSnapshot", "SemanticCandidate", "GroundingResult",
    } <= names, f"the scan found only {sorted(names)}"


def test_no_field_stores_a_frame_a_screenshot_or_a_platform_object() -> None:
    offenders = [
        f"{cls.__name__}.{name}"
        for cls in _value_types()
        for name in _offending_field_names(f.name for f in dataclasses.fields(cls))
    ]
    assert not offenders, (
        f"{offenders} look like raw sensor data or a live platform object. ADR-v2-151 "
        "keeps both out of the public contract: a candidate is a copy of what a source "
        "saw, and a stale accessibility node held across snapshots acts on the wrong "
        "element."
    )


def _unknown_annotation_names(cls: type) -> list[str]:
    bad: list[str] = []
    for f in dataclasses.fields(cls):
        # PEP 563 is on in the module, so annotations arrive as source strings.
        tokens = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", str(f.type)))
        unknown = tokens - ALLOWED_ANNOTATION_NAMES
        if unknown:
            bad.append(f"{cls.__name__}.{f.name}: {sorted(unknown)}")
    return bad


@dataclasses.dataclass(frozen=True)
class _SmuggledPlatformObject:
    """Deliberately bad: the shape the annotation guard exists to reject."""

    thing: "AXUIElement | None" = None  # type: ignore[name-defined] # noqa: F821


def test_the_annotation_guard_rejects_a_foreign_type() -> None:
    """Without this the guard could be reading empty annotations and pass on anything."""
    assert _unknown_annotation_names(_SmuggledPlatformObject)


def test_every_field_annotation_is_a_primitive_or_one_of_our_own_values() -> None:
    bad = [line for cls in _value_types() for line in _unknown_annotation_names(cls)]
    assert not bad, f"unexpected types in the public contract: {bad}"


def test_grounding_evidence_cannot_carry_private_ui_text() -> None:
    """The spec's rule: evidence explains *why*, it is not a dump of what was on
    screen. An enum makes that structural — there is nowhere to put a window title."""
    assert not dataclasses.is_dataclass(GroundingEvidence)
    for member in GroundingEvidence:
        assert isinstance(member.value, str)
        assert re.fullmatch(r"[a-z_]+", member.value), member
    assert len(GroundingEvidence) >= 5


def test_the_module_has_no_module_level_state() -> None:
    """A cache or a registry here would make two consumers of the vocabulary share
    mutable state, and the harness would replay fixtures through a dirty object."""
    tree = ast.parse(CONTRACTS_PATH.read_text(encoding="utf-8"))
    module_level_assignments = [
        node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    assert not module_level_assignments


def test_no_nan_leaks_through_any_accepted_confidence() -> None:
    """Belt and braces on the property that motivated the validation at all."""
    for value in (a_target().confidence, a_candidate().confidence):
        assert math.isfinite(value)
