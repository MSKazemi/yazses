"""The optional semantic-grounding seam on the gaze path (ADR-v2-151 phase P2).

Glance-Type answers one coarse question — *which window was the user looking at when
the hold began?* — and ``gaze/route.py`` turns that into a window the dictation lands
in. That is enough for "close this" and not enough for "click this", because a window
holds dozens of controls.

This module is the join, and it is deliberately the smallest thing that can be one:

* :class:`GazeGrounder` holds an **injected** :class:`~yazses.grounding.contracts.SemanticSource`
  and a :class:`~yazses.grounding.resolver.TargetResolver`, turns one gaze sample into a
  :class:`~yazses.grounding.contracts.TargetSnapshot`, asks the source what is under it
  and returns the resolver's tri-state answer;
* :func:`refine` collapses that answer into the two facts a consumer may act on, and its
  whole job is the guarantee in its first line: **the window is whatever the route
  decision already said**, and an exact entity appears only for a ``GROUNDED`` result.

What it does not do, on purpose:

* **No platform import.** No ``pyatspi``, no PyObjC, no UI Automation, no screen capture
  and no network — a semantic source is handed in, and ADR-v2-151 keeps the adapters
  behind the Protocol so ordinary CI runs this with a list of values. The spec's coverage
  study (phase P3) has to say what a real desktop can expose before an adapter is written,
  so nothing in the shipped daemon constructs a source today and every install keeps
  exactly the window-level behaviour it has now.
* **No action.** Grounding answers what "this" refers to. Whether the answer may be
  clicked, closed or confirmed stays downstream with the existing safety rules
  (ADR-v2-151, ADR-021).
* **No new number.** Every threshold lives on the injected ``ResolutionPolicy``; this
  module adds none, because none of them has been measured yet.
* **No failure of its own.** A source that raises, a backend that reports an impossible
  confidence, a window id that is not a usable identifier — each costs one warning and
  returns ``None``, which is the same state as "no source configured": today's behaviour.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from yazses.gaze.route import RouteDecision
from yazses.grounding import (
    CoordinateSpace,
    GroundingOutcome,
    GroundingResult,
    IntentHint,
    Point,
    SemanticSource,
    TargetResolver,
    TargetSnapshot,
    TargetSource,
)

log = logging.getLogger(__name__)

#: The space gaze geometry is expressed in: whole-desktop pixels, which is what
#: ``calibrate.CalibrationMap.predict`` returns and what the window rectangles from
#: ``gaze/desktop.py`` are already in.
#:
#: A semantic source must publish candidates in the *same* space or the resolver
#: abstains with ``SEMANTIC_SPACE_MISMATCH`` — an honest refusal rather than a
#: comparison of two unrelated pixel grids. ``version`` stays 0 here because bumping it
#: is the layout-invalidation half of ADR-v2-149 and belongs to whoever owns the display
#: topology, not to this seam: the guard on the targeter already refuses to route at all
#: while the arrangement has changed, so grounding never runs on a stale layout.
SCREEN_SPACE = CoordinateSpace("screen")


@dataclass(frozen=True)
class RefinedTarget:
    """What a consumer may act on after grounding — window first, entity only if earned.

    The shape is the regression guarantee written as a type. ``window_id`` is copied
    from the route decision and is never influenced by the semantic source, so every
    existing consumer (Glance-Type routing, window-level deixis, the destructive-confirm
    gate) reads exactly what it read before. ``entity_id`` is the *only* thing grounding
    can add, and :func:`refine` fills it for one outcome out of three.

    ``role`` is carried because it is a control type ("button", "text"), which a planner
    needs and which no privacy rule objects to. The candidate's **label is deliberately
    dropped**: it is human-visible UI text — a file name, a contact, a subject line — and
    the spec forbids the grounding trail from becoming a place private strings collect.
    """

    window_id: object | None
    entity_id: str | None = None
    role: str | None = None
    outcome: GroundingOutcome | None = None

    @property
    def is_exact(self) -> bool:
        """Whether an exact semantic entity was identified.

        The question every consumer should ask before planning an element-level action.
        ``False`` for an ambiguous or unresolved result and for a target that was never
        grounded at all, which are the same answer on purpose: "keep doing what you did
        before" is the correct handling of all three.
        """
        return self.entity_id is not None


def refine(decision: RouteDecision | None, result: GroundingResult | None) -> RefinedTarget:
    """Combine the window route with the grounding answer. Pure.

    ``result`` is ``None`` whenever grounding did not run or could not answer — no
    semantic source, low-confidence gaze, a source that raised. That case and the two
    abstention outcomes all produce a target carrying the window and no entity, so an
    ``AMBIGUOUS`` or ``UNRESOLVED`` result can never be mistaken for an exact element:
    there is no path here that reads ``alternatives``, and picking one of them is the
    guess ADR-v2-151 forbids.
    """
    window_id = decision.target if decision is not None else None
    if result is None:
        return RefinedTarget(window_id=window_id)
    if result.candidate is None or not result.is_grounded:
        return RefinedTarget(window_id=window_id, outcome=result.outcome)
    return RefinedTarget(
        window_id=window_id,
        entity_id=result.candidate.entity_id,
        role=result.candidate.role,
        outcome=GroundingOutcome.GROUNDED,
    )


class GazeGrounder:
    """Ask an injected semantic source what the user was looking *at*, or abstain.

    One instance can be shared for the life of the daemon: the resolver is frozen and
    stateless, and the only state kept here is the failure bookkeeping that stops a
    broken source writing one log line per hold.
    """

    def __init__(
        self,
        source: SemanticSource,
        *,
        resolver: TargetResolver | None = None,
        space: CoordinateSpace = SCREEN_SPACE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self._resolver = resolver if resolver is not None else TargetResolver()
        self._space = space
        self._clock = clock
        self._failure_logged = False
        #: How many grounding attempts ended in an exception. Public because "the
        #: semantic source is failing" and "the semantic source has nothing to say"
        #: are different problems with different owners (the spec's P4 evaluation
        #: reports them apart), and the second is already visible as an abstention
        #: while the first would otherwise only exist in a log line nobody reads.
        self.failures = 0

    def ground(
        self,
        *,
        window_id: object,
        point: tuple[float, float],
        confidence: float,
        hint: IntentHint | None = None,
    ) -> GroundingResult | None:
        """Ground one gaze sample, or ``None`` if the attempt itself failed.

        ``None`` is not an abstention — the resolver's abstentions come back as
        ``AMBIGUOUS``/``UNRESOLVED`` results carrying a reason. ``None`` means the seam
        could not produce an answer at all, and it is returned rather than a fabricated
        ``UnresolvedReason`` because the contract's reason vocabulary has no member for
        "the adapter raised", and inventing one here would put a crash into the metric
        that counts a platform's accessibility coverage.

        The clock is read twice on purpose. The first reading dates the gaze sample; the
        second is the moment the resolver judges it, so a source that takes longer than
        the policy's freshness budget to answer makes the target *stale* and the result
        abstains. A screen can be scrolled in that gap, and grounding against where a
        control used to be is precisely the wrong-target error the abstention exists for.
        """
        try:
            sampled_at = self._clock()
            target = TargetSnapshot(
                source=TargetSource.GAZE,
                timestamp_s=sampled_at,
                confidence=confidence,
                space=self._space,
                point=Point(float(point[0]), float(point[1])),
                window_id=self._window_key(window_id),
            )
            candidates = list(self._source.snapshot(window_id=target.window_id, region=None))
            result = self._resolver.resolve(
                target, candidates, now_s=self._clock(), hint=hint
            )
        except Exception as exc:
            self.failures += 1
            if not self._failure_logged:
                # Once per failure streak, not once per hold: a source that is broken is
                # usually broken for the whole session, and a line per dictation would
                # bury it in exactly the log someone would search to find it. The same
                # reasoning the topology guard's suspension notice uses.
                self._failure_logged = True
                log.warning(
                    "Semantic grounding failed (%s); keeping the window-level gaze "
                    "target. Dictation is unaffected.", exc,
                )
            return None
        self._failure_logged = False
        return result

    @staticmethod
    def _window_key(window_id: object) -> str | None:
        """The window id as the Protocol spells it: a non-empty string, or None.

        Desktop backends key windows by whatever their tool returns — an X11 id as an
        ``int`` from ``xdotool``, a string elsewhere — while ``TargetSnapshot`` requires
        a non-empty ``str`` so that one adapter cannot answer about window ``7`` and
        another about window ``"7"``. Anything that does not survive the conversion
        becomes None, which asks the source about no particular window rather than
        about a window called "None".
        """
        if window_id is None:
            return None
        key = str(window_id)
        return key if key else None
