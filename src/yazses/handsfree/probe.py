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
diagnostic nobody will run twice. No platform implements that seam, so the pointer row is
answered by :func:`pointer_route_facts` instead: a *prediction* from the session type, the
typing backend and the installed packages (``pointer/route.py``), refined by what the running
daemon reports about its own pointer (``yazses headpointer status``). It never opens a
pointer, a portal session or a socket of its own beyond the one status call the caller makes.

Callers refine what they get with ``dataclasses.replace``: `doctor` adds the camera verdict
and the calibration check it is willing to pay for, and the daemon adds the runtime state
only it can see.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from yazses.handsfree.observability import HandsFreeFacts
from yazses.pointer.route import plan_pointer_route

__all__ = [
    "PointerEnvironment",
    "calibration_facts",
    "face_release_findings",
    "facts_from_config",
    "gaze_target_facts",
    "pointer_facts",
    "pointer_route_facts",
    "read_pointer_environment",
]


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


def gaze_target_facts(
    facts: HandsFreeFacts,
    *,
    environ: Mapping[str, str] | None = None,
    fixed_session: Callable[[], str | None] | None = None,
    xdotool_available: Callable[[], bool] | None = None,
) -> HandsFreeFacts:
    """Record what a gaze target can be on this session (#418). Only when gaze is requested.

    Pure given its probes, read-only, no subprocess and no camera: it classifies the
    session through ``describe_host()`` and the environment, the same planner the daemon
    and ``yazses gaze status`` use, so the three cannot disagree. Total -- an unreadable
    host leaves the fields at "not asked", which the row does not print as good news.
    """
    if "gaze" not in facts.features_requested:
        return facts
    try:
        from yazses.gaze.target_semantics import describe_gaze_target

        plan = describe_gaze_target(
            environ, fixed_session=fixed_session, xdotool_available=xdotool_available
        )
    except Exception:  # noqa: BLE001 - a diagnostic must not be the thing that raises
        return facts
    return replace(
        facts,
        gaze_target_available=plan.available,
        gaze_target_reason=plan.reason,
        gaze_target_remedy=plan.remedy,
    )


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


@dataclass(frozen=True)
class PointerEnvironment:
    """The read-only facts :func:`~yazses.pointer.route.plan_pointer_route` is a function of."""

    session_type: str
    typing_backend: str | None
    xlib_available: bool | None
    display_present: bool


def read_pointer_environment(
    cfg: Any,
    *,
    environ: Mapping[str, str] | None = None,
    fixed_session: Callable[[], str | None] | None = None,
    typing_backend: Callable[[], str | None] | None = None,
    xlib_available: Callable[[], bool | None] | None = None,
) -> PointerEnvironment:
    """Read what decides the pointer backend. Read-only, no subprocess, no pointer, no portal.

    The session bucket mirrors ``platform/linux/__init__._pointer_factory`` rather than
    ``doctor``'s "Session type" line, because the factory is what the daemon actually runs:
    only ``XDG_SESSION_TYPE=wayland`` refuses XTEST, and any other session with a
    ``DISPLAY`` takes the X11 path. The OS-fixed buckets (``windows``, ``macos``) come from
    ``describe_host()`` -- the platform seam, so this module reads no ``sys.platform``.
    Every probe is injectable so the mapping is testable on a machine with no session.
    """
    env = os.environ if environ is None else environ

    def _fixed() -> str | None:
        from yazses.platform.factory import describe_host

        return describe_host().fixed_session_type

    try:
        fixed = (fixed_session or _fixed)()
    except Exception:  # noqa: BLE001 - an unreadable host is "not fixed", not a failure
        fixed = None
    kind = (env.get("XDG_SESSION_TYPE", "") or "").strip().lower()
    display = bool(env.get("DISPLAY"))
    if fixed:
        session = fixed
    elif kind == "wayland":
        session = "wayland"
    elif display:
        session = "x11"
    else:
        session = "headless"

    def _typing() -> str | None:
        from yazses.inject import registry

        injection = getattr(cfg, "injection", None)
        requested = (env.get("YAZSES_INJECTOR", "") or "").strip().lower()
        if not requested or requested == "auto":
            requested = (getattr(injection, "backend", "") or "auto").strip().lower()
        consent = (getattr(injection, "portal_consent", "") or "ask").strip().lower()
        return registry.select(registry.Env.detect(requested, consent=consent)).chosen.name

    def _xlib() -> bool | None:
        import importlib.util

        return importlib.util.find_spec("Xlib") is not None

    typing: str | None = None
    if session.startswith("wayland"):
        try:
            typing = (typing_backend or _typing)()
        except Exception:  # noqa: BLE001 - "could not determine" is a real answer here
            typing = None
    try:
        xlib = (xlib_available or _xlib)() if session == "x11" else None
    except Exception:  # noqa: BLE001
        xlib = None
    return PointerEnvironment(session, typing, xlib, display)


def pointer_route_facts(
    facts: HandsFreeFacts,
    environment: PointerEnvironment,
    *,
    daemon_running: bool,
    live: Mapping[str, Any] | None = None,
) -> HandsFreeFacts:
    """Name the pointer backend that would drive the cursor, and whether it may. Pure.

    A platform that named its own backend (``pointer_facts``) is left alone. Otherwise the
    answer is the prediction from *environment*, **overridden by the running daemon** when
    it reports a live Head-Pointer: what the daemon is actually using beats what doctor
    would have guessed, including the permission state it alone holds.

    *live* is the daemon's ``headpointer status`` reply (``None`` when it was not asked or
    did not answer). The permission wording distinguishes four situations a user cannot
    tell apart from "unknown": the daemon is not running; it is running with no active
    Head-Pointer; it is running one whose backend has no permission step; and the real
    consent state.
    """
    if facts.pointer_backend:
        return facts
    if live is not None and live.get("ok") and live.get("active") and live.get("backend"):
        consent = str(live.get("consent") or "")
        return replace(
            facts,
            pointer_backend=str(live["backend"]),
            pointer_available=True,
            pointer_certain=True,
            pointer_consent=consent,
            pointer_consent_reason=str(live.get("consent_reason") or ""),
            pointer_reason="reported by the running daemon",
        )
    route = plan_pointer_route(
        session_type=environment.session_type,
        typing_backend=environment.typing_backend,
        xlib_available=environment.xlib_available,
        display_present=environment.display_present,
    )
    # A reason the platform seam already recorded (e.g. "could not report its pointer
    # capabilities") is kept: the prediction adds to it, it does not erase it.
    reason = route.reason + (f"; {facts.pointer_reason}" if facts.pointer_reason else "")
    if not route.backend:
        return replace(
            facts,
            pointer_available=False,
            pointer_reason=reason,
            pointer_remedy=route.remedy,
        )
    if not route.needs_consent:
        consent, why = "not_required", ""
    elif not daemon_running:
        consent, why = "daemon_not_running", ""
    elif live is not None and live.get("ok") and not live.get("active"):
        consent, why = "daemon_no_pointer", str(live.get("reason") or "")[:120]
    else:
        consent, why = "daemon_no_pointer", ""
    return replace(
        facts,
        pointer_backend=route.backend,
        pointer_available=True,
        pointer_certain=route.certain,
        pointer_reason=reason,
        pointer_remedy=route.remedy,
        pointer_consent=consent,
        pointer_consent_reason=why,
    )
