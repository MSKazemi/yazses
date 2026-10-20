"""Apply an implicit refinement only when it earns it, and only atomically (#398).

``gaze/implicit.py`` can estimate a better map from clicks, and ``refined_if_better`` can
say whether a candidate beats a baseline on held-out data. Neither decides what happens
*next*: who holds the held-out samples, when the comparison runs, what a loss costs, what
a win writes, and what happens if the write fails half way. This module is that policy.
It is the difference between "an estimator exists" and "a passive estimator can never
silently make a good calibration worse" — which is the Phase 2 exit gate in
``design/eye-control/ROADMAP.md``.

## The rules, each of which is a test

* **The baseline is the explicit map and it stays put.** Nothing is written until the
  candidate wins on held-out samples by the configured margin. A loss, a tie, too little
  data, a stale display context and a failed write all leave the persisted artifact
  byte-for-byte what it was (``tests/test_gaze_refine.py`` compares bytes).
* **Training and held-out samples are disjoint by construction.** Each accepted pair is
  routed once, by position, to the estimator *or* to the held-out buffer, never both. A
  sample that taught the candidate is therefore never evidence that the candidate is
  good — the leak that makes a self-congratulating gate.
* **Persist first, then go live.** The new map is written (atomically, with the previous
  artifact kept for rollback) before the running targeter switches to it, so a crash or an
  I/O error cannot leave the daemon routing with a map the disk does not have.
* **A stale display context refines nothing.** ADR-v2-149: a refinement fitted on one
  monitor arrangement is not evidence about another. Pairs are refused while the context
  guard says the layout changed, and what was collected is discarded.
* **Empty is defined.** No samples, no held-out samples, a zero-length comparison: each is
  a named outcome (:attr:`RefinementOutcome.INSUFFICIENT_DATA`), never a division, never a
  win by default.

## What this module does not know

It does not read a camera, listen for a click or touch a file: ``persist`` and ``activate``
are injected (``gaze/store.py`` and the targeter, wired by the daemon), which is also what
lets a failure be injected in a test. The defaults in :class:`RefinementPolicy` are
conservative starting values, **not measurements** — the spec says no promotion to a
recommended feature without longitudinal field evidence (#104), and these numbers are what
that evidence would tune.
"""
from __future__ import annotations

import logging
import math
import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

from yazses.gaze.association import Association
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.implicit import (
    DEFAULT_FORGETTING,
    DEFAULT_MAX_RESIDUAL_PX,
    DEFAULT_MIN_CONFIDENCE,
    ImplicitCalibrator,
    refined_if_better,
)

__all__ = [
    "ImplicitRefiner",
    "RefinementOutcome",
    "RefinementPolicy",
    "RefinementResult",
    "RefinerStatus",
    "decide_promotion",
    "routes_to_holdout",
]

log = logging.getLogger(__name__)

#: Where a calibration came from. Mirrors ``gaze.store``; spelled here too so this module
#: needs no import of the persistence layer (it is injected).
SOURCE_EXPLICIT = "explicit"
SOURCE_IMPLICIT = "implicit"


class RefinementOutcome(str, Enum):
    """What an evaluation concluded. Exactly one per :meth:`ImplicitRefiner.evaluate`."""

    #: The candidate won held-out, was persisted, and is now the active map.
    APPLIED = "applied"
    #: The candidate did not beat the baseline by the margin. Nothing changed.
    KEPT_BASELINE = "kept_baseline"
    #: Not enough training or held-out samples yet to compare. Nothing changed.
    INSUFFICIENT_DATA = "insufficient_data"
    #: The display/camera context changed; refinement was discarded. Nothing changed.
    STALE_CONTEXT = "stale_context"
    #: The candidate won but could not be written. The baseline stays active and on disk.
    PERSIST_FAILED = "persist_failed"


@dataclass(frozen=True)
class RefinementPolicy:
    """When to compare and what a win costs. Validated, immutable, **unmeasured defaults**."""

    #: Accepted training pairs before a comparison is attempted. An affine map has three
    #: coefficients per axis, so fewer than 3 cannot even determine one.
    min_train_samples: int = 30
    #: Held-out pairs required before the comparison means anything.
    min_holdout_samples: int = 10
    #: Every Nth routed pair is held out instead of trained on (2 = half, 4 = a quarter).
    holdout_every: int = 4
    #: Held-out mean-error improvement (px) the candidate must show, and strictly > 0.
    #: ``refined_if_better``'s own default; "merely different" is a regression waiting to be
    #: blamed on something else.
    min_improvement_px: float = 1.0
    #: Bound on retained held-out pairs: recent evidence, and never an unbounded log.
    max_holdout_samples: int = 200
    #: Run the comparison after this many newly accepted pairs.
    evaluate_every: int = 10
    forgetting: float = DEFAULT_FORGETTING
    max_residual_px: float = DEFAULT_MAX_RESIDUAL_PX
    min_confidence: float = DEFAULT_MIN_CONFIDENCE

    def __post_init__(self) -> None:
        if self.min_train_samples < 3:
            raise ValueError("min_train_samples must be >= 3 (an affine map has 3 coefficients)")
        if self.min_holdout_samples < 1:
            raise ValueError("min_holdout_samples must be >= 1 (nothing can be compared on zero)")
        if self.holdout_every < 2:
            raise ValueError("holdout_every must be >= 2 (1 would leave nothing to train on)")
        if self.max_holdout_samples < self.min_holdout_samples:
            raise ValueError("max_holdout_samples must be >= min_holdout_samples")
        if self.evaluate_every < 1:
            raise ValueError("evaluate_every must be >= 1")
        for name in ("min_improvement_px", "forgetting", "max_residual_px", "min_confidence"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        if self.min_improvement_px <= 0:
            # 0 would promote a tie, or a float-noise "win" of 1e-12 px: a candidate must
            # have to save *something* to replace the user's own calibration.
            raise ValueError("min_improvement_px must be > 0")
        if not 0.0 < self.forgetting <= 1.0:
            raise ValueError("forgetting must be within (0, 1]")
        if self.max_residual_px <= 0:
            raise ValueError("max_residual_px must be > 0")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be within 0..1")


@dataclass(frozen=True)
class RefinementResult:
    """One evaluation, in derived numbers. Nothing here identifies a click or a place."""

    outcome: RefinementOutcome
    train_samples: int = 0
    holdout_samples: int = 0
    baseline_error_px: float | None = None
    candidate_error_px: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class RefinerStatus:
    """What `gaze status` can say about refinement. Counts, names and error figures only."""

    #: ``"explicit"`` or ``"implicit"`` — which kind of map is live right now.
    source: str
    train_samples: int
    holdout_samples: int
    rejected: int
    evaluations: int
    applied: int
    last_result: RefinementResult | None


# --------------------------------------------------------------------------- #
# The decision, as pure functions
# --------------------------------------------------------------------------- #


def routes_to_holdout(index: int, holdout_every: int) -> bool:
    """Whether the *index*-th routed pair (0-based) is held out rather than trained on.

    Pure, and a function of position only: the split is fixed before a pair's values are
    seen, so no click can steer itself into (or out of) the evidence that judges the
    candidate, and the same stream always splits the same way. With ``holdout_every = 4``
    pairs 3, 7, 11, ... are held out -- a quarter of them.
    """
    if holdout_every < 2:
        raise ValueError("holdout_every must be >= 2 (1 would leave nothing to train on)")
    if index < 0:
        raise ValueError("index must be >= 0")
    return index % holdout_every == holdout_every - 1


def decide_promotion(
    baseline: CalibrationMap,
    candidate: CalibrationMap,
    holdout: Sequence[tuple[tuple[float, float], tuple[float, float]]],
    *,
    train_samples: int,
    policy: RefinementPolicy,
) -> RefinementResult:
    """The fit/evaluate/accept verdict for one comparison. **Pure**: no I/O, no clock, no state.

    Same arguments, same answer; neither map nor *holdout* is modified. The three verdicts:

    * :attr:`RefinementOutcome.INSUFFICIENT_DATA` -- fewer than
      ``policy.min_train_samples`` training pairs or ``policy.min_holdout_samples``
      held-out pairs. Never a comparison on too little, never a win by default.
    * :attr:`RefinementOutcome.KEPT_BASELINE` -- the candidate did not clear the gate.
    * :attr:`RefinementOutcome.APPLIED` -- the candidate **may** be applied. It is the
      verdict, not the deed: :class:`ImplicitRefiner` still has to confirm the display
      context and write the file, and reports ``STALE_CONTEXT`` or ``PERSIST_FAILED``
      instead when either fails.

    The gate is the one :func:`~yazses.gaze.implicit.refined_if_better` defines, stated
    exactly: on the held-out pairs, both mean errors are finite, the candidate's is
    **strictly lower** than the baseline's, and the improvement
    ``baseline_error - candidate_error`` is **at least** ``policy.min_improvement_px``
    (which the policy already requires to be > 0). A tie never wins; a NaN never wins.
    This function adds no second opinion to that gate -- it only asks it.

    *holdout* must be pairs that did not train *candidate*; :func:`routes_to_holdout` is
    how the refiner guarantees that.
    """
    held = list(holdout)
    if train_samples < policy.min_train_samples or len(held) < policy.min_holdout_samples:
        return RefinementResult(
            RefinementOutcome.INSUFFICIENT_DATA,
            train_samples=train_samples,
            holdout_samples=len(held),
            reason=(
                f"needs {policy.min_train_samples} training and "
                f"{policy.min_holdout_samples} held-out pairs"
            ),
        )
    chosen, baseline_error, candidate_error = refined_if_better(
        baseline, candidate, held, min_improvement_px=policy.min_improvement_px
    )
    # `chosen is candidate` rather than a comparison of the two errors: the gate has one
    # author (`refined_if_better`). But identity alone is fooled when the two arguments are
    # the *same object* -- the gate then returns the baseline, which `is` the candidate, and
    # a map compared with itself would read as a win. Nothing new can be promoted from
    # that, so it is a keep. The finiteness check is belt and braces: a non-finite error is
    # never a win, whatever any future edit of the gate says.
    won = (
        chosen is candidate
        and candidate is not baseline
        and math.isfinite(baseline_error)
        and math.isfinite(candidate_error)
    )
    return RefinementResult(
        RefinementOutcome.APPLIED if won else RefinementOutcome.KEPT_BASELINE,
        train_samples=train_samples,
        holdout_samples=len(held),
        baseline_error_px=baseline_error,
        candidate_error_px=candidate_error,
        reason=(
            "the candidate beat the baseline on held-out samples"
            if won
            else "the candidate did not beat the baseline on held-out samples"
        ),
    )


class ImplicitRefiner:
    """Collects pairs, compares on held-out data, and promotes only a verified win.

    Thread-safe: pairs arrive on the click observer's thread while status is read from
    another. One re-entrant lock covers the lot — contention is one click per few seconds.
    """

    def __init__(
        self,
        baseline: CalibrationMap,
        policy: RefinementPolicy | None = None,
        *,
        persist: Callable[[CalibrationMap, RefinementResult], None],
        activate: Callable[[CalibrationMap], None] | None = None,
        context_valid: Callable[[], bool] | None = None,
        source: str = SOURCE_EXPLICIT,
    ) -> None:
        self._policy = policy or RefinementPolicy()
        self._persist = persist
        self._activate = activate
        self._context_check = context_valid or (lambda: True)
        self._lock = threading.RLock()
        self._baseline = baseline
        self._source = source
        self._evaluations = 0
        self._applied = 0
        self._rejected = 0
        self._last: RefinementResult | None = None
        self._reset_estimation()

    # -- state ---------------------------------------------------------------- #

    def _context_valid(self) -> bool:
        """Whether the display/camera context still applies. A check that raises says no."""
        try:
            return bool(self._context_check())
        except Exception:
            return False

    def _confirm_context(self) -> bool:
        """An unthrottled "the layout is unchanged *right now*", where one exists.

        The context callable may carry a ``confirm`` method (``refine_runtime.GuardedContext``
        does); without one there is no stronger check than the cheap one already made, so
        this is ``True``. A confirmation that raises, like a check that raises, says no.
        """
        confirm = getattr(self._context_check, "confirm", None)
        if confirm is None:
            return True
        try:
            return bool(confirm())
        except Exception:
            return False

    @property
    def baseline(self) -> CalibrationMap:
        """The map a candidate must beat: the live one."""
        return self._baseline

    @property
    def source(self) -> str:
        return self._source

    def status(self) -> RefinerStatus:
        with self._lock:
            return RefinerStatus(
                source=self._source,
                train_samples=self._calibrator.accepted,
                holdout_samples=len(self._holdout),
                rejected=self._rejected + self._calibrator.rejected,
                evaluations=self._evaluations,
                applied=self._applied,
                last_result=self._last,
            )

    def _reset_estimation(self) -> None:
        """Fresh estimator seeded from the current baseline; no held-out evidence kept."""
        policy = self._policy
        self._calibrator = ImplicitCalibrator(
            self._baseline,
            forgetting=policy.forgetting,
            max_residual_px=policy.max_residual_px,
            min_confidence=policy.min_confidence,
        )
        self._holdout: deque[tuple[tuple[float, float], tuple[float, float]]] = deque(
            maxlen=policy.max_holdout_samples
        )
        self._routed = 0
        self._since_evaluation = 0

    # -- intake --------------------------------------------------------------- #

    def observe(self, pair: Association) -> bool:
        """Route one pair to training or to held-out. ``True`` when it was kept.

        Used directly as the sink of ``ClickGazeCapture``. May trigger an evaluation, so it
        can touch the disk — rarely, and on the click thread, which nothing waits on.
        """
        with self._lock:
            if not self._context_valid():
                self._rejected += 1
                # Whatever was gathered describes another layout: it is not evidence here.
                if self._calibrator.accepted or self._holdout:
                    self._reset_estimation()
                return False

            policy = self._policy
            to_holdout = routes_to_holdout(self._routed, policy.holdout_every)
            self._routed += 1

            if to_holdout:
                kept = self._keep_holdout(pair)
            else:
                kept = self._calibrator.observe(pair.gaze, pair.click, confidence=pair.confidence)
            if not kept:
                return False

            self._since_evaluation += 1
            if self._since_evaluation >= policy.evaluate_every:
                self.evaluate()
            return True

    def _keep_holdout(self, pair: Association) -> bool:
        policy = self._policy
        if pair.confidence < policy.min_confidence:
            self._rejected += 1
            return False
        px, py = self._baseline.predict(*pair.gaze)
        if math.hypot(px - pair.click[0], py - pair.click[1]) > policy.max_residual_px:
            # The same mis-click/moved-window gate training uses, against the baseline.
            self._rejected += 1
            return False
        self._holdout.append((pair.gaze, pair.click))
        return True

    # -- the decision --------------------------------------------------------- #

    def evaluate(self) -> RefinementResult:
        """Compare candidate to baseline on held-out data; promote only a verified win."""
        with self._lock:
            result = self._evaluate_locked()
            self._evaluations += 1
            self._last = result
            self._since_evaluation = 0
            log.info(
                "Gaze refinement: %s (train %d, held-out %d%s)",
                result.outcome.value,
                result.train_samples,
                result.holdout_samples,
                ""
                if result.baseline_error_px is None or result.candidate_error_px is None
                else f", baseline {result.baseline_error_px:.1f}px vs candidate "
                f"{result.candidate_error_px:.1f}px",
            )
            return result

    def _evaluate_locked(self) -> RefinementResult:
        policy = self._policy
        train = self._calibrator.accepted
        holdout = list(self._holdout)

        if not self._context_valid():
            self._reset_estimation()
            return RefinementResult(
                RefinementOutcome.STALE_CONTEXT,
                reason="the display layout or camera changed; refinement discarded",
            )
        candidate = self._calibrator.candidate
        verdict = decide_promotion(
            self._baseline, candidate, holdout, train_samples=train, policy=policy
        )
        if verdict.outcome is not RefinementOutcome.APPLIED:
            return verdict
        won = verdict

        # The cheap context check above may be rate-limited (the daemon's guard polls the
        # display server at most every few seconds), so a layout change in the last few
        # seconds is invisible to it -- and this write is the one thing here that outlives
        # the process. Ask a check that cannot be stale, if the context offers one.
        if not self._confirm_context():
            if not self._context_valid():
                self._reset_estimation()  # the confirmation found a real change
            return RefinementResult(
                RefinementOutcome.STALE_CONTEXT,
                train_samples=train,
                holdout_samples=len(holdout),
                reason=(
                    "the display layout could not be confirmed unchanged immediately before "
                    "saving; nothing was applied"
                ),
            )
        try:
            self._persist(candidate, won)
        except Exception as exc:
            log.warning(
                "Gaze refinement won but could not be saved (%s); keeping the current "
                "calibration.", type(exc).__name__
            )
            return RefinementResult(
                RefinementOutcome.PERSIST_FAILED,
                train_samples=train,
                holdout_samples=len(holdout),
                baseline_error_px=won.baseline_error_px,
                candidate_error_px=won.candidate_error_px,
                reason=f"saving failed ({type(exc).__name__}); the previous calibration is intact",
            )

        # Only now does the running process switch. The disk already has the new map.
        self._baseline = candidate
        self._source = SOURCE_IMPLICIT
        self._applied += 1
        if self._activate is not None:
            try:
                self._activate(candidate)
            except Exception as exc:  # the file is right; a restart picks it up
                log.warning(
                    "Gaze refinement was saved but could not be activated live (%s); it "
                    "takes effect on the next start.", type(exc).__name__
                )
        # The held-out pairs just approved this map: reusing them to judge the *next*
        # candidate would be grading on the exam that was studied for.
        self._reset_estimation()
        return won
