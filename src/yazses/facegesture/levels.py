"""Per-user ACTIVE and TALK levels for the face switch, and thresholds derived between them (pure).

The resting baseline (:mod:`yazses.facegesture.calibration`) answers "where does my face sit
when I do nothing", and normalises scores against it. It cannot help when rest is already about
zero: normalising by ``1 - 0`` changes nothing, and the absolute ``hold_threshold = 0.5`` may
simply lie above anything this person's face can produce. A live trial on one webcam and one
person found exactly that -- a deliberate held jaw-open peaked well under 0.5, so the shipped
threshold never fired, while ordinary speech also reached a visible fraction of the gesture. One
person is one data point and **no default here is derived from it**: it is why this module exists,
not what it contains.

So the switch can additionally be given the user's own **active level** -- what *their* face does
when they make the gesture on purpose -- and, optionally, their **talk level** -- the most it moves
while they merely speak. From rest, active and talk this module derives the hold and release
thresholds *between* them, and **refuses, with a specific reason, whenever they are not separable
by a margin** instead of guessing. Refusal is a result, not an exception: the backend falls back
to the configured thresholds and says why.

Nothing here opens a camera, imports MediaPipe or reads a clock. It consumes
:class:`~yazses.facegesture.calibration.Reading` pairs and returns values, so every empty and
degenerate case (no frames, too few, NaN, low confidence, active not above rest, no separation,
talk overlapping the gesture) is testable from numbers. Only derived numbers are persisted --
never a frame, a mesh or the raw trace (ADR-011).

**Not a recommendation of any threshold.** Every constant below is a conditioning guard that keeps
the arithmetic well posed (a gap smaller than camera noise is not a gap). None was measured on
people, and ``design/eye-control/ROADMAP.md`` (P5.4) forbids calling a threshold recommended on
synthetic evidence. The fractions of the span at which the thresholds sit are user config, off by
default, and equally unmeasured.
"""
from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from yazses.facegesture.calibration import Baseline, Reading

__all__ = [
    "ACTIVE",
    "DEFAULT_HOLD_FRACTION",
    "DEFAULT_RELEASE_FRACTION",
    "KINDS",
    "LEAD_IN_S",
    "LEVELS_FILENAME",
    "MAX_HOLD_FRACTION",
    "MIN_HYSTERESIS",
    "MIN_SPAN",
    "TALK",
    "TALK_MARGIN",
    "Derivation",
    "GestureLevels",
    "LevelCapture",
    "LevelResult",
    "derive_thresholds",
    "describe_reason",
    "levels_path",
    "load_levels",
    "reset_levels",
    "save_level",
    "summarise_level",
]

#: Levels are stored under the data directory with this name, beside the resting baseline.
LEVELS_FILENAME = "facegesture_levels.json"

ACTIVE = "active"   # a deliberate hold of the gesture
TALK = "talk"       # speech / ordinary face movement, the thing the gesture must stay above
KINDS = (ACTIVE, TALK)

#: Seconds of ramp-up before each deliberate hold is measured by the guided CLI. The frames are
#: discarded: the gesture is still travelling, and a travelling gesture is not the level held.
LEAD_IN_S = 1.0

#: Frames a level capture must keep before it is believed (same bar as the resting baseline).
DEFAULT_MIN_SAMPLES = 15

#: Where in the span the thresholds sit when the user opted in and set nothing else. The only
#: parameter-free choices: the midpoint for hold, half of that for release. **Unmeasured.**
DEFAULT_HOLD_FRACTION = 0.5
DEFAULT_RELEASE_FRACTION = 0.25

#: The smallest active-minus-rest gap, in raw score units, that is believed. Below it the
#: gesture is not distinguishable from the camera's own frame-to-frame jitter and any threshold
#: placed in the gap would fire on noise or never. A conditioning bound, not a tuned value.
MIN_SPAN = 0.10

#: How far above the resting level, in the resting face's own robust standard deviations, the
#: hold threshold must sit (3 sigma, matching ``Baseline.separable_from``) and the release
#: threshold must sit (2 sigma: a relaxed face has to be able to fall BELOW release, or the
#: microphone would stay open).
REST_HOLD_SIGMAS = 3.0
REST_RELEASE_SIGMAS = 2.0

#: Clearance kept above the talk level, raw units. Speech varies from one sentence to the next;
#: a hold threshold sitting exactly on the captured maximum would fire on the next louder one.
TALK_MARGIN = 0.03

#: The hold threshold may sit at most this far up the span. Above it a deliberate gesture
#: clears the threshold on too few frames to be reliable, so the honest answer is "the gesture
#: and the thing it must be distinguished from overlap" and not a threshold that mostly misses.
MAX_HOLD_FRACTION = 0.8

#: The least gap kept between hold and release (raw units); smaller is not hysteresis.
MIN_HYSTERESIS = 0.02


# --------------------------------------------------------------------------- captures


@dataclass(frozen=True)
class LevelCapture:
    """One persisted level for one gesture: where the score sat while the user did one thing.

    ``level`` is the number the derivation uses -- the 75th percentile of the confident frames
    for an ACTIVE capture (a hold has ramps at both ends and a spike or two; the upper quartile
    ignores both), the maximum for a TALK capture (the conservative direction: one cough makes
    the guard stricter, never looser). ``peak`` is the highest confident frame in either case.
    """

    gesture: str
    kind: str
    level: float
    peak: float
    samples: int

    def to_dict(self) -> dict[str, object]:
        """The derived numbers only -- safe to persist."""
        return {
            "gesture": self.gesture, "kind": self.kind,
            "level": self.level, "peak": self.peak, "samples": self.samples,
        }

    @classmethod
    def from_dict(cls, raw: object) -> LevelCapture | None:
        """Parse one persisted level, or None if it is not a well-formed one. Pure and total."""
        if not isinstance(raw, Mapping):
            return None
        gesture, kind = raw.get("gesture"), raw.get("kind")
        level, peak, samples = raw.get("level"), raw.get("peak"), raw.get("samples")
        if not isinstance(gesture, str) or not gesture or kind not in KINDS:
            return None
        for v in (level, peak):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                return None
        if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
            return None
        assert isinstance(level, (int, float)) and isinstance(peak, (int, float))
        if not (0.0 <= level <= 1.0 and 0.0 <= peak <= 1.0) or peak < level:
            return None
        assert isinstance(kind, str)
        return cls(gesture=gesture, kind=kind, level=float(level), peak=float(peak), samples=samples)


@dataclass(frozen=True)
class LevelResult:
    """The outcome of one capture: a level, or the reason there is not one."""

    capture: LevelCapture | None
    reason: str            # "" on success, otherwise a short machine-stable code
    total: int             # frames offered
    kept: int              # frames the level rests on
    dropped_no_reading: int
    dropped_low_confidence: int

    @property
    def ok(self) -> bool:
        return self.capture is not None


def summarise_level(
    gesture: str,
    kind: str,
    readings: Iterable[Reading],
    *,
    confidence_floor: float = 0.0,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> LevelResult:
    """Turn frames of a deliberate hold (ACTIVE) or of speech (TALK) into one level. Pure.

    A frame is kept only if it carries a finite score and passes the confidence floor -- the
    rule :class:`~yazses.facegesture.detector.GestureSwitch` applies at run time -- so a level
    is never measured on frames the switch would refuse to act on. Every empty case is defined
    and none returns a zero level (a zero level is a *claim* the derivation would act on):

    ``bad_kind``          ``kind`` is not ``"active"`` or ``"talk"``
    ``no_frames``         nothing was offered
    ``no_reading``        frames were offered, none carried a finite score (no face, NaN)
    ``low_confidence``    readable frames existed, all below the confidence floor
    ``too_few_samples``   fewer than ``min_samples`` confident frames
    """
    total = no_reading = low_conf = 0
    kept: list[float] = []
    floor = _finite_or(confidence_floor, 0.0)
    for score, conf in readings:
        total += 1
        if score is None or not _is_finite(score):
            no_reading += 1
            continue
        if floor > 0.0 and not (conf is not None and _is_finite(conf) and conf >= floor):
            low_conf += 1
            continue
        kept.append(min(1.0, max(0.0, float(score))))

    def fail(reason: str) -> LevelResult:
        return LevelResult(None, reason, total, len(kept), no_reading, low_conf)

    if kind not in KINDS:
        return fail("bad_kind")
    if total == 0:
        return fail("no_frames")
    if total == no_reading:
        return fail("no_reading")
    if not kept:
        return fail("low_confidence")
    if len(kept) < max(1, int(min_samples)):
        return fail("too_few_samples")
    peak = max(kept)
    level = _percentile(sorted(kept), 0.75) if kind == ACTIVE else peak
    capture = LevelCapture(gesture=gesture, kind=kind, level=level, peak=peak, samples=len(kept))
    return LevelResult(capture, "", total, len(kept), no_reading, low_conf)


# --------------------------------------------------------------------------- derivation


@dataclass(frozen=True)
class Derivation:
    """Hold and release thresholds derived from rest/active/(talk), or the reason there are none."""

    hold: float | None
    release: float | None
    reason: str            # "" on success, otherwise a short machine-stable code
    detail: str            # one sentence, with the numbers, for a human
    raised_for_talk: bool = False

    @property
    def ok(self) -> bool:
        return self.hold is not None and self.release is not None


_REASONS = {
    "bad_fractions": (
        "active_hold_fraction and active_release_fraction must be finite with "
        "0 < release < hold <= {max_hold:.1f}"
    ),
    "no_rest": "there is no resting baseline for this gesture -- run `yazses facegesture calibrate`",
    "no_active": (
        "there is no active level for this gesture -- run "
        "`yazses facegesture calibrate --active`"
    ),
    "gesture_mismatch": "the stored levels belong to different gestures",
    "invalid_levels": "a stored level is not a finite number in 0..1",
    "active_not_above_rest": (
        "your deliberate gesture did not score above your resting face, so there is nothing "
        "to place a threshold between"
    ),
    "span_too_small": (
        "your deliberate gesture is less than {min_span:.2f} above your resting face, which is "
        "inside the camera's own jitter"
    ),
    "rest_noise_reaches_hold": (
        "your resting face wobbles so much that a threshold clear of it would sit above where "
        "your gesture reliably reaches"
    ),
    "talk_reaches_active": (
        "a threshold clear of your speech would sit above where your gesture reliably "
        "reaches; this gesture overlaps your talking -- try another gesture"
    ),
    "no_hysteresis_room": (
        "there is no room between your resting face and the hold threshold for a release "
        "threshold that is both above your resting noise and below the hold"
    ),
}


def describe_reason(reason: str) -> str:
    """A human sentence for a refusal code; an unknown code is returned as is. Pure."""
    template = _REASONS.get(reason)
    if template is None:
        return reason
    return template.format(max_hold=MAX_HOLD_FRACTION, min_span=MIN_SPAN)


def derive_thresholds(
    rest: Baseline | None,
    active: LevelCapture | None,
    talk: LevelCapture | None = None,
    *,
    hold_fraction: float = DEFAULT_HOLD_FRACTION,
    release_fraction: float = DEFAULT_RELEASE_FRACTION,
) -> Derivation:
    """Hold/release thresholds between the user's rest and active levels, or a refusal. Pure.

    Raw-score units throughout: the result is meant for a switch with **no** baseline
    normalisation, because the thresholds already sit between the user's own levels.

    ``hold = rest + hold_fraction * span`` and ``release = rest + release_fraction * span``,
    where ``span = active - rest``. Three guards shape or refuse the result, in order:

    * the hold threshold is lifted to at least ``REST_HOLD_SIGMAS`` of the resting face's own
      noise above rest, and the release threshold likewise ``REST_RELEASE_SIGMAS`` (a relaxed
      face must be able to fall below release, or the microphone would stay open);
    * given a ``talk`` level, hold is lifted to at least ``talk + TALK_MARGIN`` -- the derived
      hold threshold never falls into the speech range;
    * hold may not end up above ``MAX_HOLD_FRACTION`` of the span. If it would, the gesture
      cannot be told apart from what it was lifted over, and the answer is a refusal naming
      which of the two (``rest_noise_reaches_hold`` or ``talk_reaches_active``).

    Every failure returns ``hold = release = None`` and a specific ``reason``; nothing is
    clamped into a number that looks fine.
    """

    def refuse(reason: str, numbers: str = "") -> Derivation:
        return Derivation(None, None, reason, describe_reason(reason) + numbers)

    fractions = (hold_fraction, release_fraction)
    if (
        not all(_is_finite(f) for f in fractions)
        or not 0.0 < release_fraction < hold_fraction <= MAX_HOLD_FRACTION
    ):
        return refuse("bad_fractions")
    if rest is None:
        return refuse("no_rest")
    if active is None:
        return refuse("no_active")
    if active.kind != ACTIVE or (talk is not None and talk.kind != TALK):
        return refuse("invalid_levels")
    if rest.gesture != active.gesture or (talk is not None and talk.gesture != active.gesture):
        return refuse("gesture_mismatch")
    numbers = [rest.level, rest.spread, active.level, active.peak]
    if talk is not None:
        numbers += [talk.level, talk.peak]
    if not all(_is_finite(v) for v in numbers) or not all(0.0 <= v <= 1.0 for v in numbers):
        return refuse("invalid_levels")

    span = active.level - rest.level
    if span <= 0.0:
        return refuse("active_not_above_rest")
    if span < MIN_SPAN:
        return refuse("span_too_small")

    hold = rest.level + float(hold_fraction) * span
    release = rest.level + float(release_fraction) * span
    hold = max(hold, rest.level + REST_HOLD_SIGMAS * rest.spread)
    release = max(release, rest.level + REST_RELEASE_SIGMAS * rest.spread)

    raised = False
    if talk is not None and talk.level + TALK_MARGIN > hold:
        hold = talk.level + TALK_MARGIN
        raised = True

    limit = rest.level + MAX_HOLD_FRACTION * span
    if hold > limit:
        if raised and talk is not None:
            return refuse(
                "talk_reaches_active",
                f" (speech peak {talk.level:.2f} + margin {TALK_MARGIN:.2f}, "
                f"highest usable hold {limit:.2f})",
            )
        return refuse("rest_noise_reaches_hold")

    noise_floor = rest.level + REST_RELEASE_SIGMAS * rest.spread
    release = min(release, hold - MIN_HYSTERESIS)
    if release < noise_floor:
        return refuse("no_hysteresis_room")

    detail = (
        f"hold {hold:.2f} / release {release:.2f} between rest {rest.level:.2f} and "
        f"active {active.level:.2f}"
        + (f", kept above your speech peak {talk.level:.2f}" if talk is not None else "")
    )
    return Derivation(hold, release, "", detail, raised)


# --------------------------------------------------------------------------- persistence


@dataclass(frozen=True)
class GestureLevels:
    """The stored active and talk levels of one gesture (either may be absent)."""

    active: LevelCapture | None = None
    talk: LevelCapture | None = None


def levels_path(data_dir: Path) -> Path:
    """Where the levels live under ``data_dir``. Pure."""
    return Path(data_dir) / LEVELS_FILENAME


def _read(path: Path) -> list[LevelCapture]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = raw.get("levels") if isinstance(raw, Mapping) else None
    if not isinstance(entries, list):
        return []
    out = [LevelCapture.from_dict(e) for e in entries]
    return [c for c in out if c is not None]


def load_levels(path: Path) -> dict[str, GestureLevels]:
    """Every stored level, keyed by gesture. Total: any failure is ``{}``.

    A missing, unreadable, non-JSON or wrongly shaped file is "no levels" and the caller
    falls back to the configured thresholds. Malformed entries are skipped without discarding
    their well-formed neighbours; a later entry for the same gesture and kind wins.
    """
    by_key: dict[tuple[str, str], LevelCapture] = {}
    for c in _read(path):
        by_key[(c.gesture, c.kind)] = c
    gestures = {g for g, _ in by_key}
    return {
        g: GestureLevels(active=by_key.get((g, ACTIVE)), talk=by_key.get((g, TALK)))
        for g in sorted(gestures)
    }


def _write(path: Path, captures: list[LevelCapture]) -> None:
    path = Path(path)
    payload = {"version": 1, "levels": [c.to_dict() for c in captures]}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def save_level(path: Path, capture: LevelCapture) -> Path:
    """Persist ``capture``, replacing any earlier one for the same gesture and kind.

    Only derived numbers are written; other gestures' and kinds' levels are kept, and the file
    is replaced atomically so a crash mid-write cannot leave half a level behind.
    """
    kept = [c for c in _read(path) if (c.gesture, c.kind) != (capture.gesture, capture.kind)]
    kept.append(capture)
    _write(path, kept)
    return Path(path)


def reset_levels(path: Path, gesture: str | None = None) -> bool:
    """Forget one gesture's levels, or all of them. True if anything was removed."""
    path = Path(path)
    current = _read(path)
    if gesture is None:
        had = path.exists()
        path.unlink(missing_ok=True)
        return had
    remaining = [c for c in current if c.gesture != gesture]
    if len(remaining) == len(current):
        return False
    if not remaining:
        path.unlink(missing_ok=True)
    else:
        _write(path, remaining)
    return True


# --------------------------------------------------------------------------- helpers


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated ``q``-quantile of a non-empty ascending list."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _is_finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _finite_or(value: object, default: float) -> float:
    return float(value) if _is_finite(value) else default  # type: ignore[arg-type]
