"""Can the face switch let go? A checkable refusal for the stuck-open microphone (pure).

An absolute-threshold :class:`~yazses.facegesture.detector.GestureSwitch` closes the hold only
when the score falls *below* ``release_threshold``. A face whose resting score is already at
or above that level fires once and never releases: for the hold-to-talk binding that is a
microphone open indefinitely, and nothing about the configuration looks wrong. The face-switch
false-activation harness (``yazses.eyeeval``, its ``baseline-shifted-rest`` fixture) shows it.

This module turns that into a **specific, checkable** statement and nothing vaguer. It fires
on exactly three facts, each a comparison of two numbers the caller already has:

``release_unreachable``       the effective release threshold is zero or below: no score can be
                              below it, so only a lost face ends a hold.
``rest_at_or_above_hold``     a *known* resting level is at or above the effective hold
                              threshold: the relaxed face fires the switch on its own, and
                              (hold > release) never lets go.
``rest_at_or_above_release``  a *known* resting level is at or above the effective release
                              threshold: once the switch fires, it cannot release.

"Known" means a saved baseline from ``yazses facegesture calibrate``. With no baseline there is
nothing to compare, and this module says nothing -- a guess about a face nobody measured would
be a heuristic, and a guard that fires on a heuristic teaches people to dismiss it (AGENTS.md
rule 9, ADR-021). It never names a threshold to use: the remedy points at the user's own
calibration, which is also why nothing here is a recommendation (ROADMAP P5.4).

It mirrors the backend's own resolution order -- derived thresholds when ``use_active_levels``
is on and derivable, otherwise the configured pair (repaired by the switch itself), normalised
against the baseline when ``use_baseline`` is on and the baseline is usable -- by reusing
:func:`~yazses.facegesture.levels.derive_thresholds` and instantiating
:class:`~yazses.facegesture.detector.GestureSwitch` for the effective numbers, so there is one
policy and not a second one to drift.

No camera, no MediaPipe, no clock, no file: numbers in, findings out.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from yazses.facegesture.calibration import Baseline
from yazses.facegesture.detector import GestureSwitch
from yazses.facegesture.levels import (
    DEFAULT_HOLD_FRACTION,
    DEFAULT_RELEASE_FRACTION,
    GestureLevels,
    derive_thresholds,
)

__all__ = [
    "RELEASE_UNREACHABLE",
    "REST_AT_OR_ABOVE_HOLD",
    "REST_AT_OR_ABOVE_RELEASE",
    "RestFinding",
    "assess_release",
    "format_findings",
]

RELEASE_UNREACHABLE = "release_unreachable"
REST_AT_OR_ABOVE_HOLD = "rest_at_or_above_hold"
REST_AT_OR_ABOVE_RELEASE = "rest_at_or_above_release"


@dataclass(frozen=True)
class RestFinding:
    """One stuck-open risk: a stable code, the numbers in a sentence, and the way out."""

    code: str
    message: str
    remedy: str


def assess_release(
    gesture: str,
    hold_threshold: float,
    release_threshold: float,
    *,
    rest: Baseline | None = None,
    use_baseline: bool = False,
    levels: GestureLevels | None = None,
    use_active_levels: bool = False,
    hold_fraction: float = DEFAULT_HOLD_FRACTION,
    release_fraction: float = DEFAULT_RELEASE_FRACTION,
) -> tuple[RestFinding, ...]:
    """The reasons the switch configured this way could not let go. Empty means none found. Pure.

    ``rest`` is the saved resting baseline for ``gesture`` (None = never measured, so only the
    threshold pair can be judged). ``use_baseline`` / ``use_active_levels`` and the thresholds
    are the ``[facegesture]`` values as written; the effective ones are worked out here the way
    the backend works them out. Total: unreadable numbers cannot raise, and cannot produce a
    finding about a level that was never read.
    """
    hold, release, normalised, mode = _effective(
        hold_threshold, release_threshold, rest, use_baseline, levels, use_active_levels,
        hold_fraction, release_fraction,
    )

    if release <= 0.0:
        return (RestFinding(
            RELEASE_UNREACHABLE,
            f"the release threshold for {gesture} is {release:.2f}, and a score is never below "
            "zero, so the only thing that can close a hold is the face leaving the camera; "
            "the microphone would stay open until then",
            "set [facegesture] release_threshold above 0 and below hold_threshold",
        ),)

    if rest is None:
        return ()
    if use_baseline and not rest.usable and mode == "raw score":
        return ()  # the switch is inert on an unusable baseline (it says so itself): it cannot fire
    level = 0.0 if normalised else rest.level  # normalised, the resting face reads 0.0
    if not math.isfinite(level):
        return ()

    where = f"your relaxed face scores {level:.2f} on {gesture}"
    if level >= hold:
        return (RestFinding(
            REST_AT_OR_ABOVE_HOLD,
            f"{where}, at or above the hold threshold {hold:.2f} ({mode}): the switch fires "
            "without you moving, and since that is also above the release threshold "
            f"{release:.2f} it can never let go, so the microphone stays open",
            _remedy(use_baseline),
        ),)
    if level >= release:
        return (RestFinding(
            REST_AT_OR_ABOVE_RELEASE,
            f"{where}, at or above the release threshold {release:.2f} ({mode}): once the "
            "switch fires it cannot let go, so the microphone stays open",
            _remedy(use_baseline),
        ),)
    return ()


def format_findings(findings: Iterable[RestFinding]) -> list[str]:
    """Each finding as one ``message. remedy.`` line. Pure."""
    return [f"{f.message}. {f.remedy}." for f in findings]


# --------------------------------------------------------------------------- internals


def _remedy(use_baseline: bool) -> str:
    if not use_baseline:
        return (
            "set [facegesture] use_baseline = true so your baseline is divided out, or raise "
            "hold_threshold and release_threshold above your resting level, or pick a gesture "
            "your relaxed face does not reach; `yazses facegesture calibrate --active` derives "
            "thresholds from your own levels"
        )
    return (
        "raise hold_threshold and release_threshold above your resting level, pick another "
        "gesture, or recalibrate with a relaxed face"
    )


def _effective(
    hold_threshold: float,
    release_threshold: float,
    rest: Baseline | None,
    use_baseline: bool,
    levels: GestureLevels | None,
    use_active_levels: bool,
    hold_fraction: float,
    release_fraction: float,
) -> tuple[float, float, bool, str]:
    """``(hold, release, normalised, mode)`` the switch would really run with."""
    if use_active_levels:
        derived = derive_thresholds(
            rest,
            None if levels is None else levels.active,
            None if levels is None else levels.talk,
            hold_fraction=hold_fraction,
            release_fraction=release_fraction,
        )
        if derived.hold is not None and derived.release is not None:
            return derived.hold, derived.release, False, "thresholds derived from your levels"
    baseline = rest if (use_baseline and rest is not None and rest.usable) else None
    switch = GestureSwitch(
        hold_threshold, release_threshold,
        baseline=None if baseline is None else baseline.level,
    )
    hold, release = switch.thresholds
    if baseline is not None:
        return hold, release, True, "measured against your baseline"
    return hold, release, False, "raw score"
