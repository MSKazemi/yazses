"""Privacy-safe hands-free health, rendered for `doctor` and `status` — EYE-OBS-001 (#416).

Every hands-free failure this programme can have is invisible today. A camera that the
compositor handed to a video call, a MediaPipe model that never downloaded, a face switch
whose signal died four seconds ago, a calibration fitted on a monitor that has since been
unplugged — each of them ends the same way for the user: *nothing happens, and no surface
says why*. For someone whose only input method is the camera, "nothing happens" and "no
diagnostic" is the whole failure. R-08 and R-19 in `design/eye-control/RISK_REGISTER.md`
are exactly these two, and they both point here.

**What may be reported, and what may never be.** Names, states, ages, counts and
capability flags. Never a gaze coordinate, a head angle, a blendshape score, a landmark,
a frame, a window title or a transcript. That is not a style preference: `doctor` output
is what people paste into public issues, so a biometric value printed here is a biometric
value published, and ADR-019 puts face data in the category that may never leave the
machine at all. :class:`HandsFreeFacts` is the enforcement — it has no field able to hold
a sample value, so a renderer reading only from it cannot leak one even by accident, and
`tests/test_handsfree_observability_leaks_no_values.py` drives a fully populated
perception sample through the real path and asserts none of its numbers appear.

**Pure and dependency-free by contract** (AGENTS.md rule 5). No camera, no config import,
no clock, no filesystem: the facts arrive already gathered, which is what lets a test
fabricate a faulted camera, a stale switch and an unplugged monitor with no hardware at
all. `handsfree/probe.py` is the impure half that collects them.

**Three deliberate decisions, because the design documents do not settle them.**

*A row that cannot decide says "unknown", and is a SKIP rather than a WARN.* The state a
hands-free consumer is actually in lives inside the running daemon, and `doctor` is a
separate process; it genuinely cannot know whether a sample arrived 30 ms ago. Saying so
is required — a probe that cannot determine a state must never print something that reads
as OK. But making it yellow would put a permanent warning in front of every user who has
merely enabled Glance-Type and has nothing wrong, and ADR-021 is explicit that a guard is
judged on how rarely it fires. So the text says `unknown` and names the surface that does
know, and the tag stays quiet. `tests/test_handsfree_health_rows.py` holds both halves:
the word must be there, and the verdict must not move.

*No row at all when no camera feature is enabled.* `health_rows` returns an empty tuple,
which is the same contract `doctor`'s existing camera row already keeps and the first
acceptance criterion of EYE-PERM-001: on a default install every camera feature ships
off, so a hands-free block would be a paragraph about nothing on every run ever printed.

*A blocked camera is reported once.* When the camera itself is unavailable the perception
row points at the camera row instead of restating it, so one cause produces one failure
and `doctor`'s verdict counts it once.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from yazses.handsfree.safety import SafetyState, SafetyStatus, SourceHealth

__all__ = [
    "CONTINUOUS_FEATURES",
    "PAYLOAD_KEYS",
    "PERCEPTION_RUNNING",
    "PERCEPTION_STOPPED",
    "PERCEPTION_UNKNOWN",
    "DOCTOR_STATUS",
    "HandsFreeFacts",
    "Health",
    "HealthRow",
    "as_payload",
    "doctor_rows",
    "facts_from_payload",
    "health_rows",
    "render_status_lines",
]


#: The camera features that drive a *continuous* action — a moving cursor, a held mic.
#: They are the ones ADR-v2-148 requires a global stop for; Glance-Type routes a
#: dictation that the user started themselves and does not move anything on its own.
CONTINUOUS_FEATURES: tuple[str, ...] = ("headpointer", "facegesture")

#: Shared-perception source states. ``unknown`` is a real answer, not a placeholder.
PERCEPTION_RUNNING = "running"
PERCEPTION_STOPPED = "stopped"
PERCEPTION_UNKNOWN = "unknown"


class Health(Enum):
    """How one hands-free concern is doing. Values are what `status` prints."""

    #: Working, as far as anything here can tell.
    OK = "ok"
    #: Switched off, or inert because nothing asked for it. Not a problem.
    DORMANT = "dormant"
    #: **The honest "I cannot tell."** Never rendered as OK; see the module docstring.
    UNKNOWN = "unknown"
    #: Requested and not working, but nothing else is broken by it.
    DEGRADED = "degraded"
    #: Requested and faulted — the thing the user asked for is not happening.
    FAULT = "fault"


#: How each :class:`Health` reaches a `doctor` tag. ``UNKNOWN`` is deliberately SKIP and
#: not WARN — the module docstring gives the reason and a test holds it.
DOCTOR_STATUS: dict[Health, str] = {
    Health.OK: "OK",
    Health.DORMANT: "SKIP",
    Health.UNKNOWN: "SKIP",
    Health.DEGRADED: "WARN",
    Health.FAULT: "FAIL",
}


@dataclass(frozen=True)
class HealthRow:
    """One line of hands-free health: what, how, why, and what to do about it.

    ``reason`` answers *why*, ``remedy`` answers *what next* — separate fields because
    `doctor` prints both and `status` has room for one glance-sized line. A row with a
    non-OK health and an empty ``reason`` is a bug this module's tests reject: "Head
    tracking: degraded" with no cause is the failure mode observability exists to end.
    """

    label: str
    health: Health
    reason: str
    remedy: str = ""

    @property
    def detail(self) -> str:
        """``reason`` and ``remedy`` as `doctor` renders them — one per line. Pure."""
        parts = [p for p in (self.reason, self.remedy) if p]
        return "\n".join(parts)

    @property
    def line(self) -> str:
        """The single line `status` prints, newlines flattened. Pure."""
        parts = [p for p in (self.reason, self.remedy) if p]
        return "; ".join(p.replace("\n", "; ") for p in parts)


@dataclass(frozen=True)
class HandsFreeFacts:
    """Everything the renderers are allowed to know — **names, states, ages, counts.**

    Deliberately flat and deliberately primitive. Every field is a string, a bool, a
    count, an age in milliseconds, a tuple of names, or the value-free
    :class:`~yazses.handsfree.safety.SafetyStatus`; there is nowhere here to put a gaze
    point, a head angle or a blendshape score, which is how the privacy guarantee is kept
    by construction rather than by remembering.

    ``None`` means *not determined* throughout and is never read as a yes. A camera whose
    availability was never probed is not an available camera.
    """

    #: Camera features the user switched on, in `cameraperm`'s order. Empty is the
    #: shipped default and the reason nothing is reported at all.
    features_requested: tuple[str, ...] = ()
    #: Whether the camera gate said the device may be opened; ``None`` = not probed.
    camera_ready: bool | None = None
    #: Shared-perception source state — one of the three ``PERCEPTION_*`` constants.
    perception_state: str = PERCEPTION_UNKNOWN
    #: Channel *names* the newest sample carried (``("gaze", "head_pose", "face")``).
    #: ``None`` and ``()`` are different facts and must stay apart: ``()`` means the
    #: source reported and derived nothing — no face in view — while ``None`` means
    #: nobody is tracking channels at all. Collapsing them would let "we are not
    #: looking" print as "your face is not being detected".
    perception_channels: tuple[str, ...] | None = None
    #: Age of the newest sample in milliseconds; ``None`` = no sample, or not known.
    perception_age_ms: float | None = None
    #: How many consumers hold the shared source open; ``None`` = not known.
    perception_consumers: int | None = None
    perception_reason: str = ""
    #: Whether a runtime path in *this build* actually drives head pose / the face
    #: switch. ``None`` = the question was not asked; only meaningful when requested.
    head_wired: bool | None = None
    face_wired: bool | None = None
    #: Pointer backend identifier (``"x11"``, ``"portal"``, ...); ``""`` = not known.
    pointer_backend: str = ""
    pointer_relative: bool | None = None
    pointer_absolute: bool | None = None
    #: How many buttons the backend can press — a count, not a mapping.
    pointer_buttons: int | None = None
    pointer_reason: str = ""
    #: Gaze calibration verdict: ``""`` (not asked), ``"missing"``, or one of
    #: `gaze/topology.py`'s ``valid`` / ``unverified`` / ``stale``.
    calibration_validity: str = ""
    calibration_reason: str = ""
    #: Whether the user opted into the global stop + stale-signal watchdog.
    safety_configured: bool = False
    #: The staleness window in force, in milliseconds; ``None`` = not known.
    safety_window_ms: float | None = None
    #: The live gate snapshot, when one was reachable. ``None`` outside the daemon.
    safety: SafetyStatus | None = None


# --------------------------------------------------------------------------- rendering


def health_rows(facts: HandsFreeFacts) -> tuple[HealthRow, ...]:
    """Every hands-free health row, in reading order. Empty on a default install. Pure.

    Order matters: the summary state comes first because it is the one answer to "is
    hands-free input happening at all", and the component rows below it explain it.
    """
    if not facts.features_requested and not facts.safety_configured:
        return ()
    candidates = (
        _safety_row(facts),
        _perception_row(facts),
        _consumer_row(
            facts,
            label="Head tracking",
            feature="headpointer",
            wired=facts.head_wired,
            channel="head_pose",
        ),
        _consumer_row(
            facts,
            label="Face switch",
            feature="facegesture",
            wired=facts.face_wired,
            channel="face",
        ),
        _pointer_row(facts),
        _calibration_row(facts),
    )
    return tuple(row for row in candidates if row is not None)


def doctor_rows(facts: HandsFreeFacts) -> tuple[tuple[str, str, str], ...]:
    """:func:`health_rows` as `doctor`'s ``(label, status, detail)`` triples. Pure."""
    return tuple(
        (row.label, DOCTOR_STATUS[row.health], row.detail) for row in health_rows(facts)
    )


def _safety_row(facts: HandsFreeFacts) -> HealthRow | None:
    """The one ACTIVE/PAUSED/FAULTED line ADR-v2-148 asks every surface to carry."""
    label = "Hands-free safety"
    continuous = tuple(f for f in facts.features_requested if f in CONTINUOUS_FEATURES)
    if not facts.safety_configured:
        if not continuous:
            # Nothing drives a continuous action, so there is nothing for a global stop
            # to stop. Saying "off" here would be a line about a feature the user has no
            # reason to want yet.
            return None
        return HealthRow(
            label,
            Health.DEGRADED,
            f"off — {', '.join(continuous)} can drive the pointer or the microphone with "
            "no global stop and no stale-signal watchdog to consult, so a signal that "
            "dies is not what stops the action",
            "set `[handsfree_safety] enabled = true` in your config, then `yazses restart`",
        )
    window = (
        f" (a signal older than {facts.safety_window_ms:.0f} ms cannot act)"
        if facts.safety_window_ms is not None
        else ""
    )
    if facts.safety is None:
        return HealthRow(
            label,
            Health.UNKNOWN,
            f"unknown — the watchdog is switched on{window}, and only the running daemon "
            "holds the active/paused/faulted state",
            "run `yazses status` while YazSes is running",
        )
    status = facts.safety
    health = {
        SafetyState.ACTIVE: Health.OK,
        SafetyState.PAUSED: Health.DEGRADED,
        SafetyState.FAULTED: Health.FAULT,
    }[status.state]
    reason = status.state.value + window
    if status.reason:
        reason += f" — {status.reason}"
    sources = _describe_sources(status.sources)
    if sources:
        reason += f"; {sources}"
    if health is Health.OK:
        return HealthRow(label, health, reason)
    remedy = (
        "re-arm it once the signal is back — `yazses status` shows which source is holding"
        if not status.terminal
        else "the daemon is shutting down; nothing can be re-armed until it restarts"
    )
    return HealthRow(label, health, reason, remedy)


def _describe_sources(sources: Sequence[SourceHealth]) -> str:
    """Per-source health as one phrase: names, flags and ages, never a value. Pure."""
    if not sources:
        return "no source is registered"
    parts = []
    for health in sources:
        if health.faulted:
            word = "faulted"
        elif health.stale:
            word = "stale"
        elif not health.armed:
            word = "disarmed"
        else:
            word = "armed"
        age = f", {health.age_ms:.0f} ms old" if health.age_ms is not None else ", no signal"
        parts.append(f"{health.name} {word}{age}")
    return "sources: " + "; ".join(parts)


def _perception_row(facts: HandsFreeFacts) -> HealthRow | None:
    """The shared camera source: who wants it, whether it is open, and how fresh it is."""
    if not facts.features_requested:
        return None
    label = "Hands-free perception"
    wanted = f"requested by {', '.join(facts.features_requested)}"
    if facts.camera_ready is False:
        # One cause, one failure. The camera row above already carries the reason and
        # the fix; repeating them here would double `doctor`'s problem count.
        return HealthRow(
            label,
            Health.DORMANT,
            f"dormant — {wanted}, and the camera is unavailable",
            "see the Camera row above for the reason and the fix",
        )
    if facts.camera_ready is None:
        return HealthRow(
            label,
            Health.UNKNOWN,
            f"unknown — {wanted}, and camera availability was not probed here"
            + (f"; {facts.perception_reason}" if facts.perception_reason else ""),
            "run `yazses doctor`, which probes it",
        )
    if facts.perception_state == PERCEPTION_RUNNING:
        detail = [f"running — {wanted}"]
        if facts.perception_channels is None:
            detail.append("per-channel state is not being reported")
        elif facts.perception_channels:
            detail.append("signal channels: " + ", ".join(facts.perception_channels))
        else:
            detail.append("no channel is being derived right now (no face in view)")
        if facts.perception_age_ms is not None:
            detail.append(f"newest sample {facts.perception_age_ms:.0f} ms old")
        if facts.perception_consumers is not None:
            detail.append(f"{facts.perception_consumers} consumer(s)")
        if facts.perception_reason:
            detail.append(facts.perception_reason)
        return HealthRow(label, Health.OK, "; ".join(detail))
    if facts.perception_state == PERCEPTION_STOPPED:
        return HealthRow(
            label,
            Health.DEGRADED,
            f"stopped — {wanted}, and no camera session is open"
            + (f"; {facts.perception_reason}" if facts.perception_reason else ""),
            "run `yazses restart`, then `yazses status` to see whether it opens",
        )
    return HealthRow(
        label,
        Health.UNKNOWN,
        f"unknown — {wanted}; whether a camera session is open is state the running "
        "daemon holds, not something this command can see"
        + (f"; {facts.perception_reason}" if facts.perception_reason else ""),
        "run `yazses status` while YazSes is running",
    )


def _consumer_row(
    facts: HandsFreeFacts, *, label: str, feature: str, wired: bool | None, channel: str
) -> HealthRow | None:
    """Head tracking / face switch: requested, reachable, and receiving a signal?"""
    if feature not in facts.features_requested:
        return None
    if wired is False:
        return HealthRow(
            label,
            Health.DEGRADED,
            f"dormant — `[{feature}]` is on, and no runtime path in this build drives it "
            "yet, so nothing will happen however well the camera works",
            "nothing to fix locally; the wiring is tracked in the eye-control programme",
        )
    if wired is None:
        return HealthRow(
            label,
            Health.UNKNOWN,
            f"unknown — `[{feature}]` is on and whether a runtime path drives it was not "
            "determined here",
            "run `yazses features` to see whether it is wired in this build",
        )
    health = facts.safety.source(feature) if facts.safety is not None else None
    if health is not None:
        if health.faulted:
            return HealthRow(
                label, Health.FAULT, f"faulted — {health.reason or 'the backend reported a fault'}",
                "fix the cause, then re-arm — a fault never clears itself back into motion",
            )
        if health.stale:
            age = f" ({health.age_ms:.0f} ms old)" if health.age_ms is not None else ""
            return HealthRow(
                label, Health.FAULT, f"tracking invalid — the signal has gone stale{age}",
                "look back at the camera, then re-arm",
            )
        if not health.armed:
            return HealthRow(
                label, Health.DEGRADED, "disarmed — suppressed until it is explicitly re-armed",
                "re-arm it when you are ready to use it again",
            )
        age = f", newest signal {health.age_ms:.0f} ms old" if health.age_ms is not None else ""
        return HealthRow(label, Health.OK, f"tracking valid — armed{age}")
    if facts.camera_ready is False:
        return HealthRow(
            label, Health.DORMANT, "dormant — the camera is unavailable",
            "see the Camera row above for the reason and the fix",
        )
    if (
        channel
        and facts.perception_state == PERCEPTION_RUNNING
        and facts.perception_channels is not None
    ):
        if channel in facts.perception_channels:
            age = (
                f", newest sample {facts.perception_age_ms:.0f} ms old"
                if facts.perception_age_ms is not None
                else ""
            )
            return HealthRow(label, Health.OK, f"tracking valid — `{channel}` is arriving{age}")
        return HealthRow(
            label,
            Health.DEGRADED,
            f"tracking invalid — the camera is running and no `{channel}` channel is being "
            "derived from it",
            "check the lighting and that your face is in frame",
        )
    # Enabled and reachable, and nothing is measuring its freshness. The watchdog is what
    # measures it (per-source ages live on the safety gate), so naming it is the one
    # actionable thing to say — and saying "unknown" is the only honest alternative to
    # printing a clean bill of health nobody checked.
    return HealthRow(
        label,
        Health.UNKNOWN,
        "unknown — enabled and wired, and no signal freshness is being tracked for it",
        "set `[handsfree_safety] enabled = true` so its per-source age and staleness are "
        "reported here, then `yazses restart`"
        if not facts.safety_configured
        else "run `yazses status` while YazSes is running",
    )


def _pointer_row(facts: HandsFreeFacts) -> HealthRow | None:
    """Which pointer backend would move the cursor, and what it can do."""
    if "headpointer" not in facts.features_requested:
        return None
    label = "Pointer output"
    if not facts.pointer_backend:
        return HealthRow(
            label,
            Health.UNKNOWN,
            "unknown — nothing here can name the pointer backend that would move the "
            "cursor on this session"
            + (f"; {facts.pointer_reason}" if facts.pointer_reason else ""),
            "this row names the backend as soon as one ships for this platform",
        )
    caps = []
    if facts.pointer_relative is not None:
        caps.append(("relative motion" if facts.pointer_relative else "no relative motion"))
    if facts.pointer_absolute is not None:
        caps.append(("absolute motion" if facts.pointer_absolute else "no absolute motion"))
    if facts.pointer_buttons is not None:
        caps.append(f"{facts.pointer_buttons} button(s)")
    detail = facts.pointer_backend + (f" — {', '.join(caps)}" if caps else "")
    if facts.pointer_reason:
        detail += f"; {facts.pointer_reason}"
    if facts.pointer_relative is False and facts.pointer_absolute is False:
        return HealthRow(
            label,
            Health.DEGRADED,
            f"{detail} — a backend that cannot move the pointer cannot drive Head-Pointer",
            "no local fix; the backend has to grow motion support",
        )
    return HealthRow(label, Health.OK, detail)


def _calibration_row(facts: HandsFreeFacts) -> HealthRow | None:
    """Whether the stored gaze map still applies to the screens actually attached."""
    if "gaze" not in facts.features_requested or not facts.calibration_validity:
        return None
    label = "Gaze calibration"
    validity = facts.calibration_validity
    reason = facts.calibration_reason
    if validity == "missing":
        return HealthRow(
            label, Health.DEGRADED, "missing — " + (reason or "nothing has been calibrated yet"),
            "run `yazses gaze calibrate`",
        )
    if validity == "stale":
        return HealthRow(
            label, Health.DEGRADED, "stale — " + (reason or "the recorded setup no longer matches"),
            "run `yazses gaze calibrate` again on this setup",
        )
    if validity == "valid":
        return HealthRow(label, Health.OK, "valid — " + (reason or "unchanged since calibration"))
    # `unverified` from `gaze/topology.py`, and anything a future version adds. Neither
    # is evidence of a problem, and neither is evidence there is none.
    return HealthRow(
        label,
        Health.UNKNOWN,
        f"unknown — {validity}: " + (reason or "the binding could not be checked"),
        "run `yazses gaze calibrate` to bind it to this desktop",
    )


# ------------------------------------------------------------------------ the IPC wire

#: The only keys that travel from the daemon to `status`. A whitelist rather than
#: ``dataclasses.asdict`` so a field added to :class:`HandsFreeFacts` cannot reach the
#: wire before somebody has decided it is safe to print.
PAYLOAD_KEYS: tuple[str, ...] = (
    "features_requested",
    "camera_ready",
    "perception_state",
    "perception_channels",
    "perception_age_ms",
    "perception_consumers",
    "perception_reason",
    "head_wired",
    "face_wired",
    "pointer_backend",
    "pointer_relative",
    "pointer_absolute",
    "pointer_buttons",
    "pointer_reason",
    "calibration_validity",
    "calibration_reason",
    "safety_configured",
    "safety_window_ms",
    "safety",
)


def as_payload(facts: HandsFreeFacts) -> dict[str, object] | None:
    """JSON-safe facts for the daemon's status reply, or ``None`` when dormant. Pure.

    ``None`` and not an empty dict, so an install with no camera feature enabled adds no
    key to a payload fourteen callers already read.
    """
    if not facts.features_requested and not facts.safety_configured:
        return None
    out: dict[str, object] = {}
    for key in PAYLOAD_KEYS:
        value = getattr(facts, key)
        if key == "safety":
            out[key] = _safety_payload(value)
        elif isinstance(value, tuple):
            out[key] = list(value)
        else:
            out[key] = value
    return out


# The five coercions the wire needs. Each one drops an unusable value rather than
# rounding it into a fact, because the payload comes from another process and the wrong
# shape means "we do not know", never "no" and never zero.


def _names(value: object) -> tuple[str, ...] | None:
    """A tuple of names, or ``None`` for anything that is not a list of them.

    ``None`` and not ``()``: for ``perception_channels`` the two are different facts, and
    turning an unusable value into an empty tuple would tell the user their face is not
    being detected on the strength of a malformed payload.
    """
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return None


def _flag(value: object) -> bool | None:
    return None if value is None else bool(value)


def _text(value: object, default: str) -> str:
    return default if value is None else str(value)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _count(value: object) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _safety_payload(status: SafetyStatus | None) -> dict[str, object] | None:
    if status is None:
        return None
    return {
        "state": status.state.value,
        "reason": status.reason,
        "terminal": status.terminal,
        "user_paused": status.user_paused,
        "epoch": status.epoch,
        "sources": [
            {
                "name": s.name,
                "armed": s.armed,
                "stale": s.stale,
                "faulted": s.faulted,
                "reason": s.reason,
                "age_ms": s.age_ms,
                "epoch": s.epoch,
            }
            for s in status.sources
        ],
    }


def facts_from_payload(payload: Mapping[str, object] | None) -> HandsFreeFacts | None:
    """Rebuild facts from a daemon status reply, defensively. Pure.

    Defensively because the daemon on the other end may be an older build: an absent key
    keeps the field's ``None``/empty default, which reads as *not determined* rather than
    as good news, and a value of the wrong shape is dropped the same way. A `status`
    command that tracebacks against a running daemon is worse than a missing line.
    """
    # `isinstance` and not truthiness alone: the value arrives from another process, and
    # `"key" in 17` raises. A `status` that tracebacks against a running daemon is worse
    # than a missing line, and this is the shape a payload takes when a field is repurposed.
    if not payload or not isinstance(payload, Mapping):
        return None
    # Spelled out field by field rather than looped over the whitelist. The loop version
    # type-checked as `dict[str, object]` against nineteen differently-typed fields, so
    # mypy could not see a single one of them — in the function whose entire job is to
    # survive a value of the wrong shape.
    return HandsFreeFacts(
        features_requested=_names(payload.get("features_requested")) or (),
        camera_ready=_flag(payload.get("camera_ready")),
        perception_state=_text(payload.get("perception_state"), PERCEPTION_UNKNOWN),
        perception_channels=_names(payload.get("perception_channels")),
        perception_age_ms=_number(payload.get("perception_age_ms")),
        perception_consumers=_count(payload.get("perception_consumers")),
        perception_reason=_text(payload.get("perception_reason"), ""),
        head_wired=_flag(payload.get("head_wired")),
        face_wired=_flag(payload.get("face_wired")),
        pointer_backend=_text(payload.get("pointer_backend"), ""),
        pointer_relative=_flag(payload.get("pointer_relative")),
        pointer_absolute=_flag(payload.get("pointer_absolute")),
        pointer_buttons=_count(payload.get("pointer_buttons")),
        pointer_reason=_text(payload.get("pointer_reason"), ""),
        calibration_validity=_text(payload.get("calibration_validity"), ""),
        calibration_reason=_text(payload.get("calibration_reason"), ""),
        safety_configured=bool(payload.get("safety_configured", False)),
        safety_window_ms=_number(payload.get("safety_window_ms")),
        safety=_safety_from_payload(payload.get("safety")),
    )


def _safety_from_payload(value: object) -> SafetyStatus | None:
    if not isinstance(value, Mapping):
        return None
    try:
        state = SafetyState(str(value.get("state", "")))
    except ValueError:
        return None
    raw_sources = value.get("sources")
    sources: list[SourceHealth] = []
    if isinstance(raw_sources, (list, tuple)):
        for entry in raw_sources:
            if not isinstance(entry, Mapping):
                continue
            age = entry.get("age_ms")
            try:
                age_ms = None if age is None else float(age)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                age_ms = None
            sources.append(
                SourceHealth(
                    name=str(entry.get("name", "")),
                    armed=bool(entry.get("armed", False)),
                    stale=bool(entry.get("stale", True)),
                    faulted=bool(entry.get("faulted", False)),
                    reason=str(entry.get("reason", "")),
                    age_ms=age_ms,
                    epoch=int(entry.get("epoch", 0) or 0),
                )
            )
    return SafetyStatus(
        state=state,
        reason=str(value.get("reason", "")),
        terminal=bool(value.get("terminal", False)),
        user_paused=bool(value.get("user_paused", False)),
        epoch=int(value.get("epoch", 0) or 0),
        sources=tuple(sources),
    )


def render_status_lines(payload: Mapping[str, object] | None) -> list[str]:
    """The lines `yazses status` prints. Empty when no hands-free feature is on. Pure.

    Kept beside the rows rather than in the CLI so `doctor` and `status` cannot drift
    into describing the same machine differently — they render one set of rows.

    The health word is *not* prefixed onto the line. Every ``reason`` already opens with
    the state it describes — ``running``, ``stale``, ``faulted``, ``unknown``, ``valid`` —
    so prefixing it produced ``unknown — unknown — ...``, and a line that says the same
    word twice reads as a bug in the tool rather than as a fact about the machine.
    """
    facts = facts_from_payload(payload)
    if facts is None:
        return []
    return [f"  {row.label.lower()}: {row.line or row.health.value}"
            for row in health_rows(facts)]
