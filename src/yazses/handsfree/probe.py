"""Gather the hands-free health facts — the impure half of EYE-OBS-001 (#416).

`handsfree/observability.py` decides what a state *means* and how it reads; this module
is what looks at the live config, the feature registry, the platform bundle and the saved
calibration. Split for the reason `cameraperm` is split the same way: the renderer is then
testable against a fabricated faulted camera with no camera, no daemon and no monitor, and
every path that touches the machine arrives through one readable place.

**Nothing here opens a camera, and nothing here opens a pointer session.** Availability is
the camera gate's question and `doctor` already asks it once; this module is handed the
answer. The pointer backend is *named* through an optional platform seam that must report
capabilities without starting a session — on Wayland, starting one raises a portal dialog,
and a diagnostic command that makes the compositor ask the user for permission is a
diagnostic nobody will run twice. No platform implements the seam yet, so the pointer row
honestly reports ``unknown`` rather than inventing an answer.

Callers refine what they get with ``dataclasses.replace``: `doctor` adds the camera verdict
and the calibration check it is willing to pay for, and the daemon adds the runtime state
only it can see.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from yazses.handsfree.observability import HandsFreeFacts

__all__ = ["calibration_facts", "face_release_findings", "facts_from_config", "pointer_facts"]


def facts_from_config(cfg: Any, *, unwired: frozenset[str] | None = None) -> HandsFreeFacts:
    """The facts that follow from the user's settings alone.

    ``cfg`` may be ``None``: `doctor` runs with no config when the file will not parse,
    and a diagnostic that crashes on a broken config is the one that was most needed.

    ``unwired`` is the set of capability slugs that are designed but not driven by any
    runtime path in this build (`system/features.py` computes it and a test recomputes it
    from the entry points on every run, so it cannot quietly go stale). Reading it here is
    what lets the head-tracking row say *nothing in this build drives it yet* instead of
    printing a clean bill of health for a feature that cannot act.
    """
    from yazses.cameraperm import enabled_camera_features

    features = enabled_camera_features(cfg)
    section = getattr(cfg, "handsfree_safety", None)
    configured = bool(getattr(section, "enabled", False))
    window: float | None = None
    if configured:
        try:
            window = float(getattr(section, "stale_after_ms", 0) or 0) or None
        except (TypeError, ValueError):  # pragma: no cover - defensive
            window = None
    if unwired is None:
        from yazses.system.features import unwired_slugs

        unwired = unwired_slugs()
    return HandsFreeFacts(
        features_requested=features,
        safety_configured=configured,
        safety_window_ms=window,
        head_wired=("headpointer" not in unwired) if "headpointer" in features else None,
        face_wired=("facegesture" not in unwired) if "facegesture" in features else None,
    )


def calibration_facts(
    data_dir: Path,
    camera_id: str,
    *,
    read_context: Callable[[], Any] | None = None,
) -> tuple[str, str]:
    """``(validity, reason)`` for the stored gaze calibration.

    Three outcomes that must stay apart, because they send a reader to three different
    places: ``missing`` (nothing has been calibrated), one of `gaze/topology.py`'s
    ``valid``/``unverified``/``stale`` verdicts, and ``unknown`` when the question could
    not be answered at all. The last one is why this returns a pair rather than raising:
    an unreadable calibration file is a state to report, not a reason for `doctor` to
    stop.

    ``read_context`` is the seam for the current display/camera topology, which on a real
    session costs a subprocess. Injected so a test can hand over a fabricated desktop.
    """
    try:
        from yazses.gaze.store import calibration_state

        if read_context is None:
            from yazses.gaze.display import current_context

            context = current_context(camera_id=camera_id)
        else:
            context = read_context()
        calibration, check = calibration_state(data_dir, context)
    except Exception:
        return ("unknown", "the stored calibration could not be read")
    if calibration is None:
        return ("missing", "nothing has been calibrated on this machine yet")
    return (check.validity.value, check.reason)


def face_release_findings(cfg: Any, data_dir: Path) -> tuple[Any, ...]:
    """Why the face switch, as configured, could not let go -- the stuck-open microphone.

    Empty unless ``[facegesture] enabled``. Reads the saved baseline (and, when asked for, the
    saved levels) from ``data_dir`` -- a diagnostic command may read its own small calibration
    files; the daemon's start-up path may not, and does not. Only gestures bound to a *hold*
    action are judged: a gesture that selects or confirms has no microphone to leave open.
    Total: any failure is "nothing found", because a probe that raises removes the command
    that was going to explain the problem. See :mod:`yazses.facegesture.restcheck`.
    """
    try:
        face = getattr(cfg, "facegesture", None)
        if face is None or not getattr(face, "enabled", False):
            return ()
        from yazses.facegesture.calibration import baseline_path, load_baselines
        from yazses.facegesture.detector import DEFAULT_GESTURE, GESTURES
        from yazses.facegesture.levels import levels_path, load_levels
        from yazses.facegesture.restcheck import assess_release
        from yazses.facegesture.switches import HOLD_ACTIONS, parse_bindings

        primary = (getattr(face, "gesture", "") or DEFAULT_GESTURE).strip().lower()
        if primary not in GESTURES:
            primary = DEFAULT_GESTURE
        bindings, _problems = parse_bindings(
            getattr(face, "switches", None), primary, getattr(face, "mode", "full_text")
        )
        baselines = load_baselines(baseline_path(data_dir))
        levels = load_levels(levels_path(data_dir)) if getattr(face, "use_active_levels", False) else {}
        found: list[Any] = []
        for gesture, action in bindings.items():
            if action not in HOLD_ACTIONS:
                continue
            found.extend(assess_release(
                gesture,
                face.hold_threshold,
                face.release_threshold,
                rest=baselines.get(gesture),
                use_baseline=bool(getattr(face, "use_baseline", False)),
                levels=levels.get(gesture),
                use_active_levels=bool(getattr(face, "use_active_levels", False)),
                hold_fraction=face.active_hold_fraction,
                release_fraction=face.active_release_fraction,
            ))
        return tuple(found)
    except Exception:
        return ()


def pointer_facts(facts: HandsFreeFacts, platform: Any) -> HandsFreeFacts:
    """Name the pointer backend and its capabilities, if the platform can say.

    ``getattr`` against the bundle rather than an attribute, and a `Protocol`-shaped
    optional seam rather than a required one, because no platform ships a pointer backend
    yet (`pointer/base.py` is the contract; the implementations land per OS). A bundle
    that cannot answer leaves the fields untouched, and the row then says ``unknown`` —
    which is the true answer and the one thing a health probe may never replace with a
    default that reads as OK.
    """
    report = getattr(platform, "pointer_capabilities", None)
    if not callable(report):
        return facts
    try:
        caps = report()
    except Exception:
        return replace(
            facts, pointer_reason="the platform could not report its pointer capabilities"
        )
    backend = str(getattr(caps, "backend", "") or "")
    if not backend:
        return facts
    buttons = getattr(caps, "buttons", None)
    return replace(
        facts,
        pointer_backend=backend,
        pointer_relative=bool(getattr(caps, "relative_motion", False)),
        pointer_absolute=bool(getattr(caps, "absolute_motion", False)),
        pointer_buttons=len(buttons) if buttons is not None else None,
    )
