"""Per-user neutral baseline for the face-gesture switch (pure) — EYE-FACE-001.

The shipped thresholds are absolute numbers (``hold_threshold = 0.5``) and are the same for
every face. A blendshape score is not: some people rest with the jaw slightly open, a camera
angle can lift ``browInnerUp`` for the whole session, and a different landmarker build reports a
different resting level. A user whose neutral ``jawOpen`` is 0.45 is five hundredths of a point
from holding the key without moving at all, and a user whose neutral is 0.0 has to travel all the
way to 0.5. One number cannot be right for both.

So the switch can be given a **baseline**: this module turns a short capture of the user's
*relaxed* face into one, robustly, and says plainly when it cannot. The baseline is the median of
the confident frames (a blink or a swallow during the capture is an outlier, not the resting
level), and its spread is the MAD scaled to a standard deviation, which is what lets a caller ask
whether the user's neutral wobble is small next to the threshold they configured.

Nothing here opens a camera, imports MediaPipe or reads a clock. It consumes
:class:`Reading` pairs and returns values, so the whole policy is testable from numbers. Only the
derived numbers are ever persisted — never a frame, a mesh or the raw trace (ADR-011).

**Not a recommendation of any threshold.** The defaults below (the minimum sample count, the
headroom floor, the sigma multiple) are conditioning guards that keep the arithmetic well
posed, not tuned operating points: nothing in this change was measured on people, and
``design/eye-control/ROADMAP.md`` (P5.4) forbids calling a threshold recommended on synthetic
evidence.
"""
from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

#: Baselines are stored under the data directory with this name.
BASELINE_FILENAME = "facegesture_baseline.json"

#: The least headroom (``1 - baseline``) a gesture may have and still be normalised.
#: Normalising divides by the headroom, so noise is amplified by ``1 / headroom``; at 0.25
#: that is at most 4x. Below it the user's *resting* score is so close to the top of the
#: range that the gesture has nowhere left to go, and dividing would turn a rounding error
#: into a deliberate-looking movement. This is a numerical-conditioning bound, not a
#: tuning recommendation.
MIN_HEADROOM = 0.25

#: Frames a capture must keep (after dropping unreadable and low-confidence ones) before it
#: is believed. A median of two numbers is not a baseline.
DEFAULT_MIN_SAMPLES = 15

#: Scale from MAD to a standard deviation for normally distributed data.
_MAD_TO_SIGMA = 1.4826


class Reading(NamedTuple):
    """One frame as the calibration (and the switch) sees it.

    ``score`` is the gesture score, or None for no reading. ``confidence`` is the landmarker's
    confidence for the frame, or None when the source does not report one — a separate input,
    never folded into ``score``, so "the model is unsure" cannot masquerade as "the face is
    relaxed".
    """

    score: float | None
    confidence: float | None = None


@dataclass(frozen=True)
class Baseline:
    """A user's resting level for one gesture, and how steady it was."""

    gesture: str
    level: float          # median resting score, 0..1
    spread: float         # robust standard deviation of the resting score, raw units
    samples: int          # confident frames the numbers rest on

    @property
    def headroom(self) -> float:
        """The room left above the resting level, ``1 - level``."""
        return 1.0 - self.level

    @property
    def usable(self) -> bool:
        """Can scores be normalised against this at all? See :data:`MIN_HEADROOM`."""
        return (
            math.isfinite(self.level)
            and 0.0 <= self.level <= 1.0
            and self.headroom >= MIN_HEADROOM
        )

    def separable_from(self, hold_threshold: float, sigmas: float = 3.0) -> bool:
        """Does ``sigmas`` of the user's own neutral wobble stay below ``hold_threshold``?

        Both sides are on the normalised scale. False means the resting face, by itself, can
        reach the hold threshold: the calibration is real but the configured threshold cannot
        separate the user's neutral from their gesture, and the caller should say so rather
        than let the switch fire on a relaxed face. Unusable baselines are never separable.
        """
        if not self.usable or not math.isfinite(hold_threshold):
            return False
        return (sigmas * self.spread) / self.headroom < hold_threshold

    def to_dict(self) -> dict[str, object]:
        """The derived numbers only — safe to persist."""
        return {
            "gesture": self.gesture,
            "level": self.level,
            "spread": self.spread,
            "samples": self.samples,
        }

    @classmethod
    def from_dict(cls, raw: object) -> Baseline | None:
        """Parse one persisted baseline, or None if it is not a well-formed one. Pure.

        Total: a hand-edited or truncated file yields None, never an exception and never a
        half-trusted number — an unreadable baseline must fall back to the absolute
        thresholds (and say so), not crash the daemon or normalise by garbage.
        """
        if not isinstance(raw, Mapping):
            return None
        gesture = raw.get("gesture")
        level, spread, samples = raw.get("level"), raw.get("spread"), raw.get("samples")
        if not isinstance(gesture, str) or not gesture:
            return None
        for v in (level, spread):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                return None
        if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
            return None
        assert isinstance(level, (int, float)) and isinstance(spread, (int, float))
        if not 0.0 <= level <= 1.0 or spread < 0.0:
            return None
        return cls(gesture=gesture, level=float(level), spread=float(spread), samples=samples)


@dataclass(frozen=True)
class CalibrationResult:
    """The outcome of one capture: a baseline, or the reason there is not one."""

    baseline: Baseline | None
    reason: str            # "" on success, otherwise a short machine-stable code
    kept: int              # frames the baseline rests on
    dropped_no_reading: int
    dropped_low_confidence: int

    @property
    def ok(self) -> bool:
        return self.baseline is not None


def calibrate(
    gesture: str,
    readings: Iterable[Reading],
    *,
    confidence_floor: float = 0.0,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> CalibrationResult:
    """Derive a resting baseline for ``gesture`` from frames of a relaxed face. Pure.

    A frame is **kept** only if it carries a finite score and passes the confidence floor —
    the same rule :class:`~yazses.facegesture.detector.GestureSwitch` applies at run time, so
    a baseline is never measured on frames the switch would refuse to act on. With a floor
    above zero a frame that reports no confidence is dropped (unknown is not trusted).

    Every empty case is defined: no frames, no readable frames, too few kept frames and no
    headroom each return a result with ``baseline=None`` and a distinct ``reason``. None of
    them returns a zero baseline, because a zero baseline is a *claim* ("this face rests at
    nothing") that the next stage would act on.
    """
    no_reading = low_conf = 0
    kept: list[float] = []
    floor = _finite_or(confidence_floor, 0.0)
    for score, conf in readings:
        if score is None or not _is_finite(score):
            no_reading += 1
            continue
        if floor > 0.0 and not (conf is not None and _is_finite(conf) and conf >= floor):
            low_conf += 1
            continue
        kept.append(min(1.0, max(0.0, float(score))))

    def fail(reason: str) -> CalibrationResult:
        return CalibrationResult(None, reason, len(kept), no_reading, low_conf)

    if len(kept) < max(1, int(min_samples)):
        return fail("too_few_samples")
    # Lazy: this module is imported by every config load (via the gesture-name list), and
    # `statistics` drags in `decimal` and `fractions`, which a default start never needs.
    import statistics

    level = statistics.median(kept)
    spread = _MAD_TO_SIGMA * statistics.median(abs(x - level) for x in kept)
    baseline = Baseline(gesture=gesture, level=level, spread=spread, samples=len(kept))
    if not baseline.usable:
        return fail("no_headroom")
    return CalibrationResult(baseline, "", len(kept), no_reading, low_conf)


def normalise(score: float | None, level: float | None) -> float | None:
    """A raw gesture score expressed as a fraction of the room above the resting ``level``.

    ``(score - level) / (1 - level)``, so the resting face reads 0.0 and the fullest
    possible gesture reads 1.0, and the switch's existing 0..1 thresholds mean "this far
    toward the user's own maximum". Below the resting level reads 0.0, not a negative.

    ``level is None`` means no baseline and returns ``score`` unchanged — exactly the
    behaviour before calibration existed. A non-finite score, or a level with less than
    :data:`MIN_HEADROOM` of room (including 1.0, where the division would be by zero),
    returns None: no reading, never an invented number.
    """
    if score is None or not _is_finite(score):
        return None
    if level is None:
        return float(score)
    if not _is_finite(level) or not 0.0 <= level <= 1.0 - MIN_HEADROOM:
        return None
    return min(1.0, max(0.0, (float(score) - level) / (1.0 - level)))


# --------------------------------------------------------------------------- persistence


def baseline_path(data_dir: Path) -> Path:
    """Where the baselines live under ``data_dir``. Pure."""
    return Path(data_dir) / BASELINE_FILENAME


def load_baselines(path: Path) -> dict[str, Baseline]:
    """Read every persisted baseline, keyed by gesture. Total: any failure is ``{}``.

    A missing, unreadable, non-JSON or wrongly shaped file is "no baseline", and the caller
    falls back to the absolute thresholds. Individual malformed entries are skipped without
    discarding their well-formed neighbours.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = raw.get("baselines") if isinstance(raw, Mapping) else None
    if not isinstance(entries, list):
        return {}
    out: dict[str, Baseline] = {}
    for entry in entries:
        baseline = Baseline.from_dict(entry)
        if baseline is not None:
            out[baseline.gesture] = baseline
    return out


def save_baseline(path: Path, baseline: Baseline) -> Path:
    """Persist ``baseline``, replacing any earlier one for the same gesture.

    Only the derived numbers are written. Other gestures' baselines are kept, and the file
    is replaced atomically so a crash mid-write cannot leave half a baseline behind.
    """
    path = Path(path)
    merged = load_baselines(path)
    merged[baseline.gesture] = baseline
    payload = {"version": 1, "baselines": [b.to_dict() for b in merged.values()]}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def reset_baseline(path: Path, gesture: str | None = None) -> bool:
    """Forget one gesture's baseline, or all of them. True if anything was removed.

    Calibration must be repeatable and resettable (spec-eye-face-switch): this is the reset.
    """
    path = Path(path)
    current = load_baselines(path)
    if gesture is None:
        had = path.exists()
        path.unlink(missing_ok=True)
        return had
    if gesture not in current:
        return False
    del current[gesture]
    if not current:
        path.unlink(missing_ok=True)
        return True
    payload = {"version": 1, "baselines": [b.to_dict() for b in current.values()]}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return True


def _is_finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _finite_or(value: object, default: float) -> float:
    return float(value) if _is_finite(value) else default  # type: ignore[arg-type]
