"""Pure value contracts for grounding a coarse target onto a semantic UI entity.

ADR-v2-151 splits "what is the user pointing at?" into three separate concepts, and
this module is the whole of the first phase (P0) of
``design/specs/eye-grounded-targets.md``: the immutable vocabulary, nothing else.

* :class:`TargetSnapshot` — *where* the user referred, from gaze, the mouse, the head
  pointer or an explicit screen selection. One coarse observation, timestamped.
* :class:`SemanticCandidate` — *what* structured entities a semantic source (AT-SPI,
  macOS Accessibility, UI Automation, or an application's own context provider) says
  are there.
* :class:`GroundingResult` — the resolver's answer, which is deliberately **tri-state**:
  grounded, ambiguous or unresolved.

**There is no resolver here.** Ranking, the spatial envelope, intent hints and the
ambiguity gate are EYE-GROUND-002 (#442); the gaze/deixis seam is #443; the replay
harness is #445. This file must stay a vocabulary so all three can be written and
tested against it without importing each other.

**Why abstention is a type and not an exception.** ADR-v2-151 requires the resolver to
say "several plausible things" or "nothing usable" rather than guess, because a wrong
exact-element action costs the user more than a refusal does (ADR-021). An exception
would make the honest outcome the error path, and error paths get swallowed. So
:class:`GroundingOutcome` has three members, the invariants below make each one
structurally distinct, and a consumer cannot read a confidence number off a result that
did not ground.

**What is deliberately absent.**

* No screenshot, camera frame, MediaPipe result, ``pyatspi`` node, ``AXUIElement`` or
  ``IUIAutomationElement`` — ADR-v2-151 forbids a live platform object in these values,
  and ``tests/test_grounding_contracts.py`` enforces it by scanning this module's
  imports and every field annotation. A candidate is a *copy* of what a source saw.
* No network, no file, no clock. Timestamps are supplied by the caller, so every test
  is deterministic and nothing here can reach off the machine (ADR-011/ADR-019).
* No thresholds. Freshness budgets, ambiguity separation and confidence floors are
  product policy that must be evidence-driven; the spec says unit tests inject them
  explicitly, so they belong to the resolver's injected policy object, not here.

**Why the evidence type is a closed enum with no free text.** The spec warns that the
evidence record "must not become a dump of private UI text". Making it an enum means it
*cannot* carry a window title or a document fragment, so a debug log or an evaluation
report that prints evidence is safe by construction rather than by review. Per-component
scores, if #442 needs them, go in a separate scored wrapper beside the resolver.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


# --------------------------------------------------------------------------- #
# Validation helpers. Shared so every value type rejects the same nonsense the
# same way — a platform adapter dividing by a zero-size window produces NaN, and
# a NaN confidence compares False against every threshold, which silently reads
# as "below policy" in one branch and "not above policy" in another.
# --------------------------------------------------------------------------- #
def _check_unit_interval(name: str, value: float) -> None:
    """Confidences are probabilities-ish: finite and within ``[0.0, 1.0]``.

    Rejected at construction rather than clamped. Clamping would let a broken
    source announce certainty (``1e9 -> 1.0``) and a downstream consumer would
    act on it; raising puts the failure at the adapter that produced it.
    """
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be a finite value in [0.0, 1.0], got {value!r}")


def _check_timestamp(name: str, value: float) -> None:
    """Monotonic seconds: finite, sign unconstrained.

    Only non-finite values are refused. CPython documents the reference point of
    ``time.monotonic()`` as undefined, so a negative reading is not provably
    impossible on some platform and refusing one would reject a valid clock; a
    NaN or infinity, by contrast, makes every freshness subtraction meaningless.
    """
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite monotonic timestamp, got {value!r}")


def _check_identifier(name: str, value: str) -> None:
    if not value:
        raise ValueError(f"{name} must not be empty")


def _freeze_sequence(instance: object, field_name: str) -> None:
    """Normalise a declared-tuple field to an actual tuple, in place.

    ``@dataclass(frozen=True)`` stops *later* mutation; it does not stop a caller
    passing a list in the first place, and one list makes the whole value unhashable.
    The replay harness (#445) keys fixtures on these values, so the guarantee has to
    hold for every construction path, not only the classmethod constructors.
    ``object.__setattr__`` is the documented way to write a frozen field from
    ``__post_init__``.
    """
    value = getattr(instance, field_name)
    if not isinstance(value, tuple):
        object.__setattr__(instance, field_name, tuple(value))


# --------------------------------------------------------------------------- #
# Geometry. Plain numbers in one declared coordinate space — never a platform
# rectangle object.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CoordinateSpace:
    """Which pixel grid a point or rectangle is expressed in, and its generation.

    Geometry is only comparable within one space, so the spec requires an explicit
    identifier wherever geometry is present. ``version`` is the invalidation half of
    ADR-v2-149: a monitor being plugged in, a resolution change or a re-calibration
    bumps it, and an old snapshot then compares unequal to a fresh candidate instead
    of silently grounding against a layout that no longer exists.
    """

    name: str
    version: int = 0

    def __post_init__(self) -> None:
        _check_identifier("CoordinateSpace.name", self.name)
        if self.version < 0:
            raise ValueError(f"CoordinateSpace.version must be >= 0, got {self.version!r}")


@dataclass(frozen=True)
class Point:
    """A location in some :class:`CoordinateSpace`. The space is named by the owner."""

    x: float
    y: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.x) or not math.isfinite(self.y):
            raise ValueError(f"Point coordinates must be finite, got ({self.x!r}, {self.y!r})")


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle: ``(x, y)`` top-left plus a non-negative size.

    A negative width or height is refused rather than normalised. "Normalising" it
    would invent a rectangle the source never reported, and the only thing that can
    produce one is a bug in the adapter — which is worth a traceback at the seam.
    """

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        for name, value in (
            ("x", self.x), ("y", self.y), ("width", self.width), ("height", self.height),
        ):
            if not math.isfinite(value):
                raise ValueError(f"Rect.{name} must be finite, got {value!r}")
        if self.width < 0 or self.height < 0:
            raise ValueError(
                f"Rect size must be non-negative, got {self.width!r}x{self.height!r}"
            )

    def contains(self, point: Point) -> bool:
        """Half-open containment, matching ``window_at_point`` in ``gaze/zones.py``.

        (Spelled as a path, not a dotted import. ``scripts/config_status.py`` decides
        whether a config field is ever read by regex-searching ``src/yazses`` for a
        dot or quote followed by the field name, docstrings included — so a dotted
        reference to that module here silently flips the ``[gaze]`` section's
        same-named key out of its unread ledger and stales the entry.)

        Half-open (``x <= px < x + width``) so adjacent rectangles tile the plane
        without a shared edge belonging to both — two candidates claiming the same
        boundary pixel is exactly the tie the ambiguity gate should not have to break.
        A zero-size rectangle therefore contains nothing.
        """
        return (
            self.x <= point.x < self.x + self.width
            and self.y <= point.y < self.y + self.height
        )

    def intersects(self, other: Rect) -> bool:
        """Whether the two rectangles share any area. Zero-area never intersects.

        Written as ``max(start) < min(end)`` per axis rather than the shorter
        pairwise ``a.x < b.x + b.width and b.x < a.x + a.width``. The pairwise form
        is only equivalent when both widths are positive: it reports a zero-width
        rectangle *inside* another as intersecting, which would let a candidate with
        no area win the spatial envelope in #442.
        """
        return (
            max(self.x, other.x) < min(self.x + self.width, other.x + other.width)
            and max(self.y, other.y) < min(self.y + self.height, other.y + other.height)
        )

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2.0, self.y + self.height / 2.0)


# --------------------------------------------------------------------------- #
# Where the user referred.
# --------------------------------------------------------------------------- #
class TargetSource(Enum):
    """The modality that produced a :class:`TargetSnapshot`.

    Closed on purpose. An ``OTHER`` bucket would collapse provenance — the one thing
    ADR-v2-151 says consumers must not lose — and every downstream policy that treats
    coarse webcam gaze differently from a deliberate mouse click would quietly stop
    being able to tell them apart. Adding a modality means adding a member here, which
    is a diff someone reviews.
    """

    GAZE = "gaze"
    MOUSE = "mouse"
    HEAD_POINTER = "head_pointer"
    SELECTION = "selection"


@dataclass(frozen=True)
class TargetSnapshot:
    """One coarse observation of where the user was referring, at one instant.

    ``point``, ``bounds`` and ``window_id`` are all optional because a real source
    fails: a webcam frame with no face yields a snapshot with a confidence and nothing
    else, and that is a legitimate input the resolver answers ``UNRESOLVED`` to. What
    is *not* optional is honesty about geometry — if any geometry is present, the
    coordinate space must be named, because a point with no space is a number that
    looks comparable and is not.
    """

    source: TargetSource
    timestamp_s: float
    confidence: float
    space: CoordinateSpace | None = None
    point: Point | None = None
    bounds: Rect | None = None
    window_id: str | None = None

    def __post_init__(self) -> None:
        _check_timestamp("TargetSnapshot.timestamp_s", self.timestamp_s)
        _check_unit_interval("TargetSnapshot.confidence", self.confidence)
        if (self.point is not None or self.bounds is not None) and self.space is None:
            raise ValueError(
                "TargetSnapshot.space is required when point or bounds is present — "
                "geometry without a coordinate space cannot be compared to a candidate"
            )
        if self.window_id is not None:
            _check_identifier("TargetSnapshot.window_id", self.window_id)

    @property
    def has_geometry(self) -> bool:
        return self.point is not None or self.bounds is not None


# --------------------------------------------------------------------------- #
# What is there.
# --------------------------------------------------------------------------- #
class SemanticSourceKind(Enum):
    """Where a candidate came from, in the spec's semantic-first preference order.

    The order in this enum is the order the spec lists; it carries no weights. How
    much an exact accessibility node outranks a geometry-only window fallback is
    resolver policy (#442), not a property of the vocabulary.
    """

    ACCESSIBILITY = "accessibility"
    APPLICATION = "application"
    SELECTION = "selection"
    WINDOW = "window"


@dataclass(frozen=True)
class SemanticCandidate:
    """One structured entity a semantic source reported — a copy, never a live node.

    ``entity_id`` is only promised to be stable *for the snapshot that produced it*.
    Accessibility trees renumber, and a consumer that caches one across snapshots and
    acts on it later would act on whatever now holds that id.

    ``label`` may contain what the user can see on screen, which is user content: it
    exists so an intent hint like "click Save" has something to match, and the spec's
    privacy rule forbids publishing it in evaluation reports. It is never copied into
    :class:`GroundingEvidence`.
    """

    source: SemanticSourceKind
    entity_id: str
    role: str
    captured_at_s: float
    confidence: float
    space: CoordinateSpace | None = None
    bounds: Rect | None = None
    label: str | None = None
    actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _check_identifier("SemanticCandidate.entity_id", self.entity_id)
        _check_identifier("SemanticCandidate.role", self.role)
        _check_timestamp("SemanticCandidate.captured_at_s", self.captured_at_s)
        _check_unit_interval("SemanticCandidate.confidence", self.confidence)
        _freeze_sequence(self, "actions")
        if self.bounds is not None and self.space is None:
            raise ValueError(
                "SemanticCandidate.space is required when bounds is present — "
                "geometry without a coordinate space cannot be compared to a target"
            )


@runtime_checkable
class SemanticSource(Protocol):
    """Read-only access to whatever structured entities a platform can describe.

    Every platform adapter — Linux AT-SPI, macOS Accessibility, Windows UI Automation,
    or an application's own provider — implements exactly this, so the resolver never
    imports ``pyatspi``, PyObjC or a Win32 binding and stays testable in ordinary CI
    with a list of :class:`SemanticCandidate` values.

    It reads. It has no method that clicks, focuses or types: grounding answers what
    "this" refers to, and action risk stays downstream (ADR-v2-151, ADR-021).
    """

    def snapshot(
        self,
        *,
        window_id: str | None,
        region: Rect | None,
    ) -> Sequence[SemanticCandidate]:
        """Candidates in *region* of *window_id*; empty when the source knows nothing."""
        ...


# --------------------------------------------------------------------------- #
# The answer.
# --------------------------------------------------------------------------- #
class GroundingEvidence(Enum):
    """Why the resolver preferred a candidate — a closed vocabulary, no free text.

    Safe to log, safe to aggregate in an evaluation report, and impossible to turn
    into a leak of a window title or a document fragment.
    """

    INSIDE_TARGET_REGION = "inside_target_region"
    NEAREST_TO_TARGET_POINT = "nearest_to_target_point"
    WINDOW_MATCH = "window_match"
    ROLE_MATCH = "role_match"
    LABEL_HINT_MATCH = "label_hint_match"
    EXACT_ACCESSIBILITY_FOCUS = "exact_accessibility_focus"
    SOURCE_QUALITY = "source_quality"


class GroundingOutcome(Enum):
    """The tri-state result. ``AMBIGUOUS`` and ``UNRESOLVED`` are successes."""

    GROUNDED = "grounded"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class GroundingResult:
    """What a target grounded to, or honestly why it did not.

    This is ADR-v2-151's ``GroundedTarget`` widened into its two abstention cases, so
    that a caller cannot receive an object whose mere existence implies success. The
    invariants make the three states structurally distinct:

    * ``GROUNDED`` carries exactly one ``candidate``; ``alternatives`` may hold the
      runners-up a later UX layer might offer.
    * ``AMBIGUOUS`` carries no ``candidate`` and at least two ``alternatives`` — one
      plausible candidate is not an ambiguity, it is an answer.
    * ``UNRESOLVED`` carries nothing at all, including no evidence: there was no
      preference to explain.

    ``resolution_confidence`` is pinned to ``0.0`` unless grounded. A consumer that
    reads the number without checking the outcome then gets the safe answer rather
    than the confidence of a candidate the resolver refused to choose. It is a single
    number about *this resolution* and deliberately does not replace
    ``candidate.source``: the ADR forbids collapsing provenance into one float.

    Prefer the :meth:`grounded`, :meth:`ambiguous` and :meth:`unresolved` constructors;
    they make the intended state impossible to get wrong.
    """

    outcome: GroundingOutcome
    target: TargetSnapshot
    candidate: SemanticCandidate | None = None
    alternatives: tuple[SemanticCandidate, ...] = ()
    resolution_confidence: float = 0.0
    evidence: tuple[GroundingEvidence, ...] = ()

    def __post_init__(self) -> None:
        _check_unit_interval("GroundingResult.resolution_confidence", self.resolution_confidence)
        _freeze_sequence(self, "alternatives")
        _freeze_sequence(self, "evidence")
        if self.outcome is GroundingOutcome.GROUNDED:
            if self.candidate is None:
                raise ValueError("a GROUNDED result must name the candidate it grounded to")
            return
        if self.candidate is not None:
            raise ValueError(f"a {self.outcome.value.upper()} result must not name a candidate")
        if self.resolution_confidence != 0.0:
            raise ValueError(
                f"a {self.outcome.value.upper()} result must report 0.0 confidence, "
                f"got {self.resolution_confidence!r}"
            )
        if self.outcome is GroundingOutcome.AMBIGUOUS:
            if len(self.alternatives) < 2:
                raise ValueError(
                    "an AMBIGUOUS result must carry at least two plausible candidates; "
                    f"got {len(self.alternatives)}"
                )
        elif self.alternatives or self.evidence:
            raise ValueError("an UNRESOLVED result must carry no candidates and no evidence")

    @property
    def is_grounded(self) -> bool:
        return self.outcome is GroundingOutcome.GROUNDED

    @classmethod
    def grounded(
        cls,
        target: TargetSnapshot,
        candidate: SemanticCandidate,
        *,
        resolution_confidence: float,
        evidence: Sequence[GroundingEvidence] = (),
        alternatives: Sequence[SemanticCandidate] = (),
    ) -> GroundingResult:
        return cls(
            outcome=GroundingOutcome.GROUNDED,
            target=target,
            candidate=candidate,
            alternatives=tuple(alternatives),
            resolution_confidence=resolution_confidence,
            evidence=tuple(evidence),
        )

    @classmethod
    def ambiguous(
        cls,
        target: TargetSnapshot,
        candidates: Sequence[SemanticCandidate],
        *,
        evidence: Sequence[GroundingEvidence] = (),
    ) -> GroundingResult:
        return cls(
            outcome=GroundingOutcome.AMBIGUOUS,
            target=target,
            alternatives=tuple(candidates),
            evidence=tuple(evidence),
        )

    @classmethod
    def unresolved(cls, target: TargetSnapshot) -> GroundingResult:
        return cls(outcome=GroundingOutcome.UNRESOLVED, target=target)
