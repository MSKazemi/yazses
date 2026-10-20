"""The hands-free control panel, as data — EYE-SETTINGS-001 (#420).

A person who cannot use a keyboard or mouse reliably needs one place that answers four
questions without them having to read a log: *is hands-free input on, is it healthy, how do I
stop it, and what do I do when it breaks?* This module is that place **as a view-model**: it
decides which rows exist, what each state says and what each button does. The Qt window
(`settingsui/handsfree_panel.py`) and the terminal rendering (`yazses handsfree status`) both
draw it and decide nothing, so they cannot describe one machine differently.

**Pure and dependency-free by contract** (AGENTS.md rule 5). No Qt, no camera, no config
import, no clock, no filesystem, no socket: everything arrives in :class:`PanelInputs`, already
gathered, and everything the panel can *do* leaves as an :class:`ActionSpec` — a description of
an IPC call and/or a config write that the caller performs. That is what lets a test fabricate
a faulted pointer, a stale calibration and a Wayland session with no hardware at all.

**Opening the panel never opens the camera.** The inputs are the daemon's existing ``status``
reply, the Head-Pointer's existing ``status`` reply, the saved config, and the facts
`handsfree/probe.py` already gathers for `doctor` (which read a device node's permissions and a
file, never a frame). Nothing in this module can ask for more.

**Every action takes no pointer position (ADR-v2-148).** An :class:`ActionSpec` carries a
method name and at most a boolean — never a coordinate, never a target. So each one can be
bound to a voice command, a face switch, a keyboard shortcut or a script for somebody who
cannot aim, and the CLI spelling of each is on the spec (``cli``).

**Four rules the wording follows**, because the people this is for are the ones a vague panel
fails hardest:

* *State is a word, never a colour.* Every row carries one of :data:`STATUS_WORDS`, and the
  sentence beside it says what it means. A renderer may add colour; it may not be the only
  carrier of state.
* *Unknown is not OK.* A fact nobody determined reads ``UNKNOWN`` and says who knows. A
  backend that does not exist reads ``NOT AVAILABLE`` with the platform's own reason, never a
  default that looks healthy.
* *FAULTED always offers a way out.* The recovery action is enabled whenever the daemon can be
  reached, and says what to fix first and that re-arming never replays an earlier movement.
* *Stopping is never harder than starting.* Pause is enabled in every state in which anything
  hands-free is running, including the states in which the global gate is off.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from yazses.facegesture.detector import GESTURES
from yazses.facegesture.switches import (
    ACTIONS as SWITCH_ACTIONS,
)
from yazses.facegesture.switches import (
    UNMAP,
    legacy_action,
    parse_bindings,
)
from yazses.handsfree.observability import (
    HEAD_STATES,
    HandsFreeFacts,
    Health,
    HealthRow,
    health_rows,
)
from yazses.handsfree.safety import SafetyState

__all__ = [
    "ACTION_LABELS",
    "CAMERA_FEATURES",
    "STATUS_WORDS",
    "WIRED_SWITCH_ACTIONS",
    "ActionSpec",
    "ConfigSet",
    "ConfigTableArray",
    "FeatureFact",
    "FeatureRow",
    "IpcCall",
    "MappingModel",
    "MappingPlan",
    "MappingRow",
    "Overall",
    "PanelInputs",
    "PanelModel",
    "Row",
    "StateBanner",
    "build_panel",
    "merge_facts",
    "plan_mapping",
    "render_text",
    "stop_without_state",
    "wired_switch_actions",
]

#: The camera-driven capabilities the panel lets somebody switch, in reading order:
#: ``(slug, label, what it does in one clause)``.
CAMERA_FEATURES: tuple[tuple[str, str, str], ...] = (
    ("headpointer", "Head-Pointer", "moves the mouse pointer when you move your head"),
    ("facegesture", "Face switch", "turns a facial movement into a key press"),
    ("gaze", "Gaze (Glance-Type)", "sends dictation to the window you are looking at"),
)

#: The only words a row's state is spoken in. Colour may repeat one; it may not replace one.
STATUS_WORDS: dict[str, str] = {
    "ok": "OK",
    "off": "OFF",
    "unknown": "UNKNOWN",
    "attention": "NEEDS ATTENTION",
    "problem": "PROBLEM",
    "unavailable": "NOT AVAILABLE",
}

_HEALTH_TO_WORD: dict[Health, str] = {
    Health.OK: "ok",
    Health.DORMANT: "off",
    Health.UNKNOWN: "unknown",
    Health.DEGRADED: "attention",
    Health.FAULT: "problem",
}

#: Plain-language names for the face-switch actions (``switches.ACTIONS``).
ACTION_LABELS: dict[str, str] = {
    "hold_to_talk": "Hold to dictate",
    "hold_to_command": "Hold to give a command",
    "select": "Select / click",
    "confirm": "Confirm",
    "cancel": "Cancel",
    "pause_pointer": "Pause hands-free input",
    UNMAP: "Not mapped",
}

#: The switch actions the daemon always implements. The daemon builds its handler table in
#: `core/daemon.py::_build_face_gesture_source`; `tests/test_handsfree_panel.py` builds the
#: real thing for every action and fails if this and the daemon disagree, so the panel cannot
#: offer an action that does nothing.
#: `select` needs the Head-Pointer running to have anything to click and `confirm` / `cancel`
#: need something pending to answer; each says so in `yazses facegesture status` instead of
#: staying silent, which is why they count as wired.
WIRED_SWITCH_ACTIONS: tuple[str, ...] = (
    "hold_to_talk", "hold_to_command", "select", "confirm", "cancel",
)

#: How long the eyes must stay shut before an eyes-closed switch counts. `facegesture/detector.py`
#: already says this gesture "needs a long `min_hold_frames`" to tell a deliberate closure from
#: the ~15 involuntary blinks a minute, but the shipped `min_hold_frames = 3` is 0.2 s at 15 fps
#: -- inside a blink. A config-file user can read that comment; a person binding the gesture
#: from this panel never sees the key, so the mapping itself raises it. PROVISIONAL and
#: unmeasured in YazSes: chosen to sit well above a spontaneous blink, which the literature
#: commonly puts at roughly 0.1-0.4 s.
EYES_CLOSED_MIN_HOLD_S = 0.8


def eyes_closed_min_hold_frames(fps: int) -> int:
    """The smallest ``min_hold_frames`` that holds an eyes-closed switch for
    :data:`EYES_CLOSED_MIN_HOLD_S` at ``fps`` (clamped to the config's 1..60). Pure."""
    fps = min(60, max(1, int(fps)))
    # The epsilon keeps 0.8 * 15 (= 12.000000000000002 in floating point) at 12, not 13.
    return max(1, math.ceil(EYES_CLOSED_MIN_HOLD_S * fps - 1e-9))


def _seconds(frames: int, fps: int) -> str:
    return f"{frames / min(60, max(1, int(fps))):.1f} s"


def wired_switch_actions(safety_configured: bool) -> tuple[str, ...]:
    """The switch actions that actually do something, given the global-stop setting. Pure.

    ``pause_pointer`` needs the global gate: with ``[handsfree_safety]`` off the daemon has
    nothing for it to pause and leaves it unwired.
    """
    return WIRED_SWITCH_ACTIONS + (("pause_pointer",) if safety_configured else ())


# ----------------------------------------------------------------------------- the inputs


@dataclass(frozen=True)
class FeatureFact:
    """What the settings system knows about one camera capability."""

    slug: str
    label: str
    #: ``enabled`` as the saved config says it.
    enabled: bool
    #: False = designed but no runtime path drives it in this build.
    wired: bool = True
    experimental: bool = False
    #: Optional packages it needs that cannot be imported here.
    missing_packages: tuple[str, ...] = ()
    #: Why this environment can never supply it (a strict snap), or ``""``.
    blocked: str = ""
    #: ``True``/``False`` = a change is staged in the settings window; ``None`` = none.
    staged: bool | None = None


@dataclass(frozen=True)
class PanelInputs:
    """Everything the panel is allowed to know. Names, states, flags — no sample values."""

    #: Could the daemon's socket be reached at all?
    daemon_reachable: bool = False
    features: tuple[FeatureFact, ...] = ()
    #: ``[handsfree_safety] enabled`` as saved.
    safety_configured: bool = False
    #: ``[headpointer] dwell_enabled`` as saved.
    dwell_configured: bool = False
    #: Merged health facts (see :func:`merge_facts`).
    facts: HandsFreeFacts = field(default_factory=HandsFreeFacts)
    #: The camera gate's verdict text, from `cameraperm` — not a probe of its own.
    camera_reason: str = ""
    camera_remedy: str = ""
    #: The ``headpointer status`` IPC reply, or ``None`` when it could not be asked.
    headpointer: Mapping[str, Any] | None = None
    #: ``[facegesture]`` as saved.
    switches: tuple[Mapping[str, Any], ...] = ()
    primary_gesture: str = "jaw_open"
    mode: str = "full_text"
    use_baseline: bool = False
    #: ``[facegesture] min_hold_frames`` and ``fps`` as saved: an eyes-closed binding needs a
    #: hold longer than a blink (:data:`EYES_CLOSED_MIN_HOLD_S`).
    min_hold_frames: int = 3
    fps: int = 15
    #: ``"stored"`` / ``"missing"`` / ``""`` (not asked) for the primary gesture's baseline.
    baseline: str = ""
    #: ``(message, remedy)`` pairs for a face switch that could not let go (a stuck-open
    #: microphone): a saved resting level at or above the effective release threshold, or an
    #: unreachable release threshold. Empty = none found. See ``facegesture/restcheck.py``.
    release_issues: tuple[tuple[str, str], ...] = ()


# ----------------------------------------------------------------------------- the outputs


class Overall(Enum):
    """The one answer to "is hands-free input happening?". Values are what is printed."""

    OFF = "off"
    NOT_RUNNING = "not running"
    UNGATED = "running without a global stop"
    ACTIVE = "active"
    PAUSED = "paused"
    FAULTED = "faulted"


@dataclass(frozen=True)
class IpcCall:
    """One daemon call. ``params`` never holds a position — it holds at most a boolean."""

    method: str
    params: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class ConfigSet:
    """One scalar config write (``set_config_key``)."""

    section: str
    key: str
    value: object


@dataclass(frozen=True)
class ConfigTableArray:
    """Replace every ``[[name]]`` table with ``entries`` (``set_config_table_array``)."""

    name: str
    entries: tuple[tuple[tuple[str, str], ...], ...]


@dataclass(frozen=True)
class ActionSpec:
    """A button: what it says, whether it can be pressed, and what pressing it does."""

    id: str
    label: str
    #: ``stop`` | ``recover`` | ``adjust``
    kind: str
    enabled: bool
    #: Why it cannot be pressed — shown beside the disabled button, never hidden.
    why_disabled: str = ""
    #: One sentence on what it does, for the accessible description.
    help: str = ""
    ipc: IpcCall | None = None
    config: tuple[ConfigSet | ConfigTableArray, ...] = ()
    #: The terminal spelling, so the same action is reachable by voice/script/switch.
    cli: str = ""
    #: True if the change reaches a running daemon only after ``yazses restart``.
    needs_restart: bool = False
    #: Write ``config`` even if the running daemon declines the live change. Only ever set for
    #: the safe direction (turning a click off): that must stick whatever the daemon says.
    config_always: bool = False


@dataclass(frozen=True)
class StateBanner:
    state: Overall
    #: The sentence read first.
    headline: str
    detail: str = ""


@dataclass(frozen=True)
class Row:
    """One line of health: a label, a state word, what it means, and what to do."""

    label: str
    status: str  # a key of STATUS_WORDS
    text: str
    remedy: str = ""

    @property
    def word(self) -> str:
        return STATUS_WORDS[self.status]


@dataclass(frozen=True)
class FeatureRow:
    """One camera capability and the single action that flips it."""

    slug: str
    label: str
    summary: str
    status: str
    text: str
    #: ``None`` when it cannot be flipped from here (the reason is in ``text``).
    desired: bool | None = None
    button: str = ""
    experimental: bool = False

    @property
    def word(self) -> str:
        return STATUS_WORDS[self.status]


@dataclass(frozen=True)
class MappingRow:
    gesture: str
    gesture_label: str
    action: str  # "" when unmapped
    action_label: str
    note: str = ""


@dataclass(frozen=True)
class MappingModel:
    rows: tuple[MappingRow, ...]
    #: Every action a gesture may be given, with whether it does anything in this build.
    choices: tuple[tuple[str, str, bool, str], ...]
    #: Problems in the saved ``[[facegesture.switches]]`` (entries the daemon will ignore).
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class PanelModel:
    banner: StateBanner
    #: ``pause`` / ``resume`` / ``recenter`` — big, no-position, always in this order.
    actions: tuple[ActionSpec, ...]
    #: Dwell, independently of motion: the two actions, one of which is enabled.
    dwell: tuple[ActionSpec, ...]
    #: Global stop on/off (a config write; takes effect after a restart).
    safety_toggle: ActionSpec
    features: tuple[FeatureRow, ...]
    health: tuple[Row, ...]
    mapping: MappingModel
    #: Standing honest notes (nothing is on by default; what restart means).
    notes: tuple[str, ...] = ()

    def action(self, action_id: str) -> ActionSpec | None:
        for spec in (*self.actions, *self.dwell, self.safety_toggle):
            if spec.id == action_id:
                return spec
        return None

    @property
    def primary(self) -> ActionSpec | None:
        """The one action the state calls for — the default focus. ``None`` if none helps."""
        wanted = {
            Overall.ACTIVE: "pause",
            Overall.UNGATED: "pause",
            Overall.PAUSED: "resume",
            Overall.FAULTED: "resume",
        }.get(self.banner.state)
        return self.action(wanted) if wanted else None


# --------------------------------------------------------------------------- fact merging


def merge_facts(static: HandsFreeFacts, live: HandsFreeFacts | None) -> HandsFreeFacts:
    """Overlay what the running daemon knows on what the config and the OS say. Pure.

    ``static`` comes from `handsfree/probe.py` (camera verdict, pointer capabilities, stored
    calibration); ``live`` from the daemon's ``status`` reply (consumers, freshness, the gate).
    A field the daemon did not determine keeps the static answer — the daemon payload's
    ``camera_ready`` and ``calibration_*`` are deliberately blank, because a status poll must
    not touch the disk — and a field it did determine wins, because the daemon is the only
    process that can see it.
    """
    if live is None:
        return static
    return replace(
        static,
        perception_state=live.perception_state,
        perception_channels=live.perception_channels,
        perception_age_ms=live.perception_age_ms,
        perception_consumers=live.perception_consumers,
        perception_reason=live.perception_reason or static.perception_reason,
        perception_backend=live.perception_backend or static.perception_backend,
        perception_failure_kind=live.perception_failure_kind or static.perception_failure_kind,
        head_wired=live.head_wired if live.head_wired is not None else static.head_wired,
        face_wired=live.face_wired if live.face_wired is not None else static.face_wired,
        head_built=live.head_built if live.head_built is not None else static.head_built,
        face_built=live.face_built if live.face_built is not None else static.face_built,
        gaze_built=live.gaze_built if live.gaze_built is not None else static.gaze_built,
        head_state=live.head_state or static.head_state,
        head_state_reason=live.head_state_reason or static.head_state_reason,
        head_age_ms=live.head_age_ms if live.head_age_ms is not None else static.head_age_ms,
        # The daemon names the backend it is actually using and the permission state only it
        # holds; both beat a prediction made from the session type. `pointer_available` and
        # the consent pair travel together, so one never overrides without the others.
        pointer_available=(
            live.pointer_available if live.pointer_available is not None
            else static.pointer_available
        ),
        pointer_consent=live.pointer_consent or static.pointer_consent,
        pointer_consent_reason=(
            live.pointer_consent_reason if live.pointer_consent
            else static.pointer_consent_reason
        ),
        pointer_backend=live.pointer_backend or static.pointer_backend,
        pointer_relative=(
            live.pointer_relative if live.pointer_relative is not None else static.pointer_relative
        ),
        pointer_absolute=(
            live.pointer_absolute if live.pointer_absolute is not None else static.pointer_absolute
        ),
        pointer_buttons=(
            live.pointer_buttons if live.pointer_buttons is not None else static.pointer_buttons
        ),
        pointer_reason=live.pointer_reason or static.pointer_reason,
        camera_ready=live.camera_ready if live.camera_ready is not None else static.camera_ready,
        calibration_validity=live.calibration_validity or static.calibration_validity,
        calibration_reason=live.calibration_reason or static.calibration_reason,
        gaze_target_available=(
            live.gaze_target_available
            if live.gaze_target_available is not None
            else static.gaze_target_available
        ),
        gaze_target_reason=live.gaze_target_reason or static.gaze_target_reason,
        gaze_target_remedy=live.gaze_target_remedy or static.gaze_target_remedy,
        gaze_target_capabilities=(
            live.gaze_target_capabilities or static.gaze_target_capabilities
        ),
        safety_configured=live.safety_configured or static.safety_configured,
        safety_window_ms=(
            live.safety_window_ms if live.safety_window_ms is not None else static.safety_window_ms
        ),
        safety=live.safety if live.safety is not None else static.safety,
        # Only the daemon knows what a face-switch action last did; dropping it here left
        # `doctor` (which merges) without the row `yazses status` (which does not) printed.
        switch_actions=live.switch_actions or static.switch_actions,
    )


# ----------------------------------------------------------------------------- the build


def _hp_active(hp: Mapping[str, Any] | None) -> bool:
    return bool(hp) and bool(hp.get("ok")) and bool(hp.get("active"))  # type: ignore[union-attr]


def _enabled(inputs: PanelInputs, slug: str) -> bool:
    return any(f.slug == slug and f.enabled for f in inputs.features)


def _requested(inputs: PanelInputs) -> bool:
    return any(f.enabled for f in inputs.features) or inputs.safety_configured


def overall_state(inputs: PanelInputs) -> StateBanner:
    """Collapse everything into the one banner. Pure."""
    if not _requested(inputs):
        return StateBanner(
            Overall.OFF,
            "Hands-free camera controls are off.",
            "Nothing is using the camera. Nothing here turns on by itself — switch one on "
            "below when you want it.",
        )
    if not inputs.daemon_reachable:
        return StateBanner(
            Overall.NOT_RUNNING,
            "YazSes is not running, so hands-free input is not active.",
            "Start it with `yazses start`. Settings you change here are saved and apply "
            "when it starts.",
        )
    hp = inputs.headpointer
    status = inputs.facts.safety
    if status is not None:
        reason = status.reason
        if status.state is SafetyState.ACTIVE:
            return StateBanner(
                Overall.ACTIVE,
                "Active — hands-free input is allowed to act.",
                "You can press Pause at any time. It needs no pointing: use the keyboard "
                "shortcut, `yazses handsfree pause`, or a face-switch mapped to pause.",
            )
        if status.state is SafetyState.PAUSED:
            return StateBanner(
                Overall.PAUSED,
                "Paused — no hands-free input will act."
                + (f" ({reason})" if reason else ""),
                "Press Resume when you are ready. Nothing restarts by itself.",
            )
        return StateBanner(
            Overall.FAULTED,
            "Faulted — hands-free input was stopped" + (f": {reason}." if reason else "."),
            "Fix the cause shown below, then press Recover. Recovering never replays an "
            "earlier movement: the first camera frame afterwards does nothing.",
        )
    if _hp_active(hp):
        assert hp is not None
        hp_state = str(hp.get("state", ""))
        if hp_state == "faulted" or hp.get("fault"):
            return StateBanner(
                Overall.FAULTED,
                "Faulted — the Head-Pointer was stopped"
                + (f": {hp.get('fault')}." if hp.get("fault") else "."),
                "Fix the cause shown below, then press Recover. Recovering never replays an "
                "earlier movement.",
            )
        if hp.get("paused") or hp_state == "paused":
            return StateBanner(
                Overall.PAUSED,
                "Paused — the Head-Pointer will not move or click.",
                "Press Resume when you are ready. The global stop is off, so this pauses "
                "the Head-Pointer only.",
            )
        return StateBanner(
            Overall.UNGATED,
            "Running without a global stop.",
            "The global stop and stale-signal watchdog are off, so Pause here stops the "
            "Head-Pointer only, and a camera that goes quiet is not what stops it. "
            "Turn the global stop on below.",
        )
    reason = ""
    if hp is not None and hp.get("reason"):
        reason = f" ({hp['reason']})"
    return StateBanner(
        Overall.NOT_RUNNING,
        "Camera controls are switched on, but none is running." + reason,
        "Run `yazses doctor` to see why. Pause and Resume have nothing to act on.",
    )


#: The one call every Pause button makes, shared so the pre-read fallback cannot drift from it.
_PAUSE_IPC = IpcCall("handsfree", (("action", "pause"),))
_PAUSE_CLI = "yazses handsfree pause"


def stop_without_state() -> ActionSpec:
    """Pause, for the moment before the window has read anything (pure).

    The window appears at once and reads the daemon on a worker thread, which can take seconds
    on a real desktop. A person who opens it *because* the pointer is running away must not be
    told "the state has not been read yet" by the one button they came for. This is the same
    call the model's Pause makes, enabled unconditionally: the daemon says what it stopped (or
    that nothing hands-free was running), and a stop that is not needed is harmless.
    """
    return ActionSpec(
        id="pause",
        label="Pause hands-free input",
        kind="stop",
        enabled=True,
        help="Stops every hands-free input it can reach. Takes no pointer position.",
        ipc=_PAUSE_IPC,
        cli=_PAUSE_CLI,
    )


def _actions(inputs: PanelInputs, banner: StateBanner) -> tuple[ActionSpec, ...]:
    reachable = inputs.daemon_reachable
    hp_on = _hp_active(inputs.headpointer)
    gated = inputs.facts.safety is not None
    state = banner.state
    running = state in (Overall.ACTIVE, Overall.UNGATED, Overall.PAUSED, Overall.FAULTED)
    nothing = "YazSes is not running." if not reachable else "Nothing hands-free is running."

    # Stop. Enabled in every state in which something is running, and never gated on a
    # camera signal: a stop that needs a healthy camera is not a stop.
    if not running:
        pause_why = nothing
    elif state is Overall.PAUSED:
        pause_why = "Already paused."
    else:
        pause_why = ""
    pause = ActionSpec(
        id="pause",
        label="Pause hands-free input",
        kind="stop",
        enabled=not pause_why,
        why_disabled=pause_why,
        help=(
            "Stops every hands-free input from moving the pointer, clicking or opening "
            "the microphone. Takes no pointer position."
            if gated
            else "Stops the Head-Pointer from moving or clicking. The global stop is off, so "
            "this does not reach the face switch."
        ),
        ipc=_PAUSE_IPC,
        cli=_PAUSE_CLI,
    )

    if not running:
        resume_why = nothing
    elif state in (Overall.ACTIVE, Overall.UNGATED):
        resume_why = "Already active." if state is Overall.ACTIVE else "Nothing is paused."
    else:
        resume_why = ""
    faulted = state is Overall.FAULTED
    resume = ActionSpec(
        id="resume",
        label="Recover (re-arm)" if faulted else "Resume hands-free input",
        kind="recover" if faulted else "stop",
        enabled=not resume_why,
        why_disabled=resume_why,
        help=(
            "Clears the fault and re-arms hands-free input once the signal is back. The "
            "first camera frame afterwards never moves or clicks. Takes no pointer position."
        ),
        ipc=IpcCall("handsfree", (("action", "resume"),)),
        cli="yazses handsfree resume",
    )

    if not hp_on:
        recenter_why = (
            "YazSes is not running." if not reachable else "The Head-Pointer is not running."
        )
    else:
        recenter_why = ""
    recenter = ActionSpec(
        id="recenter",
        label="Recenter Head-Pointer",
        kind="adjust",
        enabled=not recenter_why,
        why_disabled=recenter_why,
        help=(
            "Treats the way you are sitting now as straight ahead. No motion and no click "
            "while it happens. Takes no pointer position."
        ),
        ipc=IpcCall("headpointer", (("action", "recenter"),)),
        cli="yazses headpointer recenter",
    )
    return (pause, resume, recenter)


def _dwell(inputs: PanelInputs) -> tuple[ActionSpec, ...]:
    hp = inputs.headpointer
    live = hp.get("dwell_enabled") if _hp_active(hp) and hp is not None else None
    on = bool(live) if live is not None else inputs.dwell_configured
    hp_enabled = _enabled(inputs, "headpointer")
    refusal = ""
    if hp is not None and hp.get("notice"):
        refusal = str(hp["notice"])
    off_why = "" if on else "Dwell-click is already off."
    on_why = ""
    if on:
        on_why = "Dwell-click is already on."
    elif not hp_enabled:
        on_why = "Turn the Head-Pointer on first — dwell-click is part of it."
    elif refusal:
        on_why = refusal
    persist_off = (ConfigSet("headpointer", "dwell_enabled", False),)
    persist_on = (ConfigSet("headpointer", "dwell_enabled", True),)
    return (
        ActionSpec(
            id="dwell_off",
            label="Turn dwell-click off",
            kind="adjust",
            enabled=not off_why,
            why_disabled=off_why,
            help="The pointer still moves; it will never click on its own. Takes effect now "
            "and is saved.",
            ipc=IpcCall("headpointer", (("action", "dwell"), ("enabled", False))),
            config=persist_off,
            config_always=True,
            cli="yazses headpointer dwell off",
        ),
        ActionSpec(
            id="dwell_on",
            label="Turn dwell-click on",
            kind="adjust",
            enabled=not on_why,
            why_disabled=on_why,
            help="Clicks when you hold still, with a ring on screen first. Takes effect now "
            "and is saved.",
            ipc=IpcCall("headpointer", (("action", "dwell"), ("enabled", True))),
            config=persist_on,
            cli="yazses headpointer dwell on",
        ),
    )


def _safety_toggle(inputs: PanelInputs) -> ActionSpec:
    if inputs.safety_configured:
        return ActionSpec(
            id="safety_off",
            label="Turn the global stop off",
            kind="adjust",
            enabled=True,
            help="Removes the shared pause and the stale-signal watchdog. Pause then reaches "
            "the Head-Pointer only. Saved now; applies after `yazses restart`.",
            config=(ConfigSet("handsfree_safety", "enabled", False),),
            needs_restart=True,
        )
    return ActionSpec(
        id="safety_on",
        label="Turn the global stop on",
        kind="adjust",
        enabled=True,
        help="One Pause for every hands-free input, and a watchdog that stops the pointer "
        "when the camera signal goes quiet. Saved now; applies after `yazses restart`.",
        config=(ConfigSet("handsfree_safety", "enabled", True),),
        needs_restart=True,
    )


def _feature_rows(inputs: PanelInputs) -> tuple[FeatureRow, ...]:
    by_slug = {f.slug: f for f in inputs.features}
    rows: list[FeatureRow] = []
    for slug, label, summary in CAMERA_FEATURES:
        fact = by_slug.get(slug)
        if fact is None:
            continue
        staged = ""
        if fact.staged is not None and fact.staged != fact.enabled:
            staged = (
                " A change is staged: it will turn "
                + ("ON" if fact.staged else "OFF")
                + " when you press Apply."
            )
        if not fact.wired:
            rows.append(FeatureRow(
                slug, label, summary, "unavailable",
                "Designed but not connected in this build, so turning it on would do nothing.",
            ))
            continue
        if fact.blocked and not fact.enabled:
            rows.append(FeatureRow(
                slug, label, summary, "unavailable",
                f"Cannot be turned on here: {fact.blocked}",
            ))
            continue
        if fact.enabled and fact.missing_packages:
            rows.append(FeatureRow(
                slug, label, summary, "attention",
                "Switched on but not working: missing "
                + ", ".join(fact.missing_packages)
                + ". Press Apply to install them." + staged,
                desired=False, button=f"Turn {label} off", experimental=False,
            ))
            continue
        if fact.enabled:
            rows.append(FeatureRow(
                slug, label, summary, "ok",
                "On." + staged, desired=False, button=f"Turn {label} off",
            ))
            continue
        rows.append(FeatureRow(
            slug, label, summary, "off",
            "Off — nothing uses the camera for this." + staged,
            desired=True, button=f"Turn {label} on", experimental=fact.experimental,
        ))
    return tuple(rows)


def _head_pointer_rows(inputs: PanelInputs) -> list[Row]:
    """The Head-Pointer and its pointer output, from its own status reply. Pure."""
    if not _enabled(inputs, "headpointer"):
        return []
    hp = inputs.headpointer
    if not inputs.daemon_reachable or hp is None:
        # Only the Head-Pointer's own row: the Pointer output row comes from the shared
        # health rows, which carry the same session-type prediction `doctor` prints.
        return [
            Row("Head-Pointer", "unknown", "YazSes is not running, so its state is not known."),
        ]
    if not hp.get("ok"):
        return [Row(
            "Head-Pointer", "unknown",
            f"Could not read its state: {hp.get('reason') or 'no reply'}.",
        )]
    if not hp.get("active"):
        reason = str(hp.get("reason") or "no reason was reported")
        return [
            Row("Head-Pointer", "unavailable", f"Not running: {reason}",
                "Run `yazses doctor` for the cause."),
            Row("Pointer output", "unavailable", reason,
                "Nothing to fix in settings if this says the platform has no pointer backend."),
        ]
    state = str(hp.get("state") or "unknown")
    pieces = [
        f"state {state}" + (f" ({hp['reason']})" if hp.get("reason") else ""),
        "centred" if hp.get("calibrated") else "not centred yet — use Recenter",
        "clutch held" if hp.get("clutched") else "clutch released",
        "dwell-click on" if hp.get("dwell_enabled") else "dwell-click off",
    ]
    # The word comes from `observability.HEAD_STATES`, the one table `doctor` and `yazses
    # status` also read, so a state cannot be a warning here and a failure there. This
    # branch used to carry its own opinion: `denied` was a PROBLEM in the window and a WARN in
    # `doctor`, and `waiting` (no usable sample yet) was OK. Only the remedy wording is the
    # window's own, because it names this window's buttons.
    entry = HEAD_STATES.get(state)
    status = _HEALTH_TO_WORD[entry[0]] if entry is not None else "unknown"
    remedy = entry[2] if entry is not None else "Run `yazses headpointer status`."
    if hp.get("fault"):
        status, remedy = "problem", "Fix the cause, then press Recover."
        pieces.append(f"fault: {hp['fault']}")
    elif state == "pending_consent":
        remedy = "Answer the desktop's permission dialog; the pointer starts by itself."
    elif state == "denied":
        remedy = "Restart YazSes and approve the permission dialog."
    elif state == "unavailable":
        status, remedy = "unavailable", "Nothing to fix in settings; dictation is unaffected."
    elif state in ("lost", "suppressed"):
        remedy = "Look at the camera; if it stays like this press Recover."
    elif state == "paused" or hp.get("paused"):
        status, remedy = "attention", "Press Resume when you are ready."
    rows = [Row("Head-Pointer", status, "; ".join(pieces), remedy)]
    backend = str(hp.get("backend") or "")
    consent = str(hp.get("consent") or "")
    why = str(hp.get("consent_reason") or "")
    if backend and consent == "pending_consent":
        rows.append(Row(
            "Pointer output", "attention",
            f"{backend} — waiting for your permission" + (f": {why}" if why else "."),
            "Answer the desktop's permission dialog; the pointer starts by itself.",
        ))
    elif backend and consent == "denied":
        rows.append(Row(
            "Pointer output", "attention",
            f"{backend} — permission was not given" + (f": {why}" if why else "."),
            "Restart YazSes and approve the permission dialog.",
        ))
    elif backend and consent == "unavailable":
        rows.append(Row(
            "Pointer output", "unavailable",
            f"{backend} — the desktop offers no pointer" + (f": {why}" if why else "."),
        ))
    elif backend and consent == "granted":
        rows.append(Row("Pointer output", "ok", f"{backend} — permission granted."))
    elif backend:
        rows.append(Row("Pointer output", "ok", f"{backend} — connected."))
    else:
        rows.append(Row("Pointer output", "unknown", "Running, but the backend did not name itself."))
    if hp.get("notice"):
        rows.append(Row("Dwell-click", "attention", str(hp["notice"])))
    return rows


def _baseline_row(inputs: PanelInputs) -> Row | None:
    if not _enabled(inputs, "facegesture"):
        return None
    label = "Face switch baseline"
    if not inputs.use_baseline:
        return Row(
            label, "off",
            "Not in use — the switch compares against a fixed threshold, not against your "
            "relaxed face.",
            "To personalise it: `yazses facegesture calibrate`, then set "
            "`[facegesture] use_baseline = true`.",
        )
    if inputs.baseline == "stored":
        return Row(label, "ok", "In use — a stored baseline for your relaxed face applies.")
    if inputs.baseline == "missing":
        return Row(
            label, "attention",
            "Switched on but no baseline is stored, so the fixed threshold is being used.",
            "Run `yazses facegesture calibrate`.",
        )
    return Row(label, "unknown", "Whether a baseline is stored was not checked.")


def _camera_row(inputs: PanelInputs) -> Row | None:
    if not any(f.enabled for f in inputs.features):
        return None
    ready = inputs.facts.camera_ready
    if ready is True:
        return Row("Camera", "ok", inputs.camera_reason or "Camera access is allowed.")
    if ready is False:
        return Row(
            "Camera", "problem", inputs.camera_reason or "The camera is unavailable.",
            inputs.camera_remedy or "Run `yazses doctor` for the fix.",
        )
    return Row(
        "Camera", "unknown",
        inputs.camera_reason or "Camera access was not determined.",
        inputs.camera_remedy or "Run `yazses doctor`, which checks it.",
    )


def _health(inputs: PanelInputs) -> tuple[Row, ...]:
    rows: list[Row] = []
    cam = _camera_row(inputs)
    if cam is not None:
        rows.append(cam)
    hp_rows = _head_pointer_rows(inputs)
    have_hp_pointer = any(r.label == "Pointer output" for r in hp_rows)
    for item in health_rows(inputs.facts):
        if item.label == "Pointer output" and have_hp_pointer:
            continue  # the Head-Pointer's own reply is more specific than "unknown"
        rows.append(_from_health(item))
    rows.extend(hp_rows)
    base = _baseline_row(inputs)
    if base is not None:
        rows.append(base)
    for message, remedy in inputs.release_issues:
        rows.append(Row("Face switch release", "problem", message[:1].upper() + message[1:], remedy))
    return tuple(rows)


def _from_health(item: HealthRow) -> Row:
    return Row(item.label, _HEALTH_TO_WORD[item.health], item.reason, item.remedy)


# ------------------------------------------------------------------------------- mapping


def _gesture_label(gesture: str) -> str:
    return gesture.replace("_", " ").capitalize()


def _current_bindings(inputs: PanelInputs) -> tuple[dict[str, str], list[str]]:
    return parse_bindings(list(inputs.switches), inputs.primary_gesture, inputs.mode)


def _mapping(inputs: PanelInputs) -> MappingModel:
    bindings, problems = _current_bindings(inputs)
    wired = set(wired_switch_actions(inputs.safety_configured))
    rows = []
    for gesture in GESTURES:
        action = bindings.get(gesture, "")
        note = ""
        if action and action not in wired:
            note = (
                "Does nothing in this build."
                if action != "pause_pointer"
                else "Does nothing while the global stop is off."
            )
        elif action and gesture == "eyes_closed":
            floor = eyes_closed_min_hold_frames(inputs.fps)
            if inputs.min_hold_frames < floor:
                note = (
                    f"Counts after only {_seconds(inputs.min_hold_frames, inputs.fps)} -- an "
                    f"ordinary blink can trigger it. Press Set to raise the hold to "
                    f"{_seconds(floor, inputs.fps)}."
                )
        rows.append(MappingRow(
            gesture, _gesture_label(gesture), action,
            ACTION_LABELS.get(action, "Not mapped") if action else "Not mapped", note,
        ))
    choices = []
    for action in (*SWITCH_ACTIONS, UNMAP):
        if action == UNMAP or action in wired:
            choices.append((action, ACTION_LABELS[action], True, ""))
        elif action == "pause_pointer":
            choices.append((
                action, ACTION_LABELS[action], False,
                "Turn the global stop on first — there is nothing for it to pause otherwise.",
            ))
        else:
            choices.append((
                action, ACTION_LABELS[action], False,
                "Not connected in this build, so a gesture mapped to it would do nothing.",
            ))
    return MappingModel(tuple(rows), tuple(choices), tuple(problems))


@dataclass(frozen=True)
class MappingPlan:
    """The outcome of asking for one gesture to be given one action."""

    ok: bool
    reason: str = ""
    #: The full replacement for ``[[facegesture.switches]]`` when ``ok``.
    action: ActionSpec | None = None
    #: Anything the write changes beyond the table, in one sentence for the person ("" = none).
    note: str = ""


def plan_mapping(inputs: PanelInputs, gesture: str, action: str) -> MappingPlan:
    """Validate "map ``gesture`` to ``action``" and return the config write, or the refusal.

    Refuses — rather than coercing to a neighbour — an unknown gesture, an unknown action,
    and an action that does nothing in this build, because binding a facial movement to the
    wrong action is worse than binding it to none (the same posture as ``parse_bindings``).
    The resulting table is round-tripped through ``parse_bindings`` before it is offered, so
    what the panel writes is, by construction, what the daemon will read.
    """
    gesture = (gesture or "").strip().lower()
    action = (action or "").strip().lower()
    if gesture not in GESTURES:
        return MappingPlan(False, f"{gesture!r} is not a gesture. Choose one of: "
                           + ", ".join(GESTURES) + ".")
    if action != UNMAP and action not in SWITCH_ACTIONS:
        return MappingPlan(False, f"{action!r} is not an action. Choose one of: "
                           + ", ".join((*SWITCH_ACTIONS, UNMAP)) + ".")
    if action != UNMAP and action not in wired_switch_actions(inputs.safety_configured):
        for key, _label, ok, why in _mapping(inputs).choices:
            if key == action and not ok:
                return MappingPlan(False, why)
    bindings, _ = _current_bindings(inputs)
    wanted = dict(bindings)
    if action == UNMAP:
        wanted.pop(gesture, None)
    else:
        wanted[gesture] = action

    legacy = legacy_action(inputs.mode)
    entries: list[tuple[tuple[str, str], ...]] = []
    for name in GESTURES:
        target = wanted.get(name)
        if name == inputs.primary_gesture:
            if target == legacy:
                continue
            entries.append((("gesture", name), ("intent", target or UNMAP)))
        elif target is not None:
            entries.append((("gesture", name), ("intent", target)))
    # The round trip: the table we are about to write must parse back to exactly `wanted`.
    again, problems = parse_bindings(
        [dict(e) for e in entries], inputs.primary_gesture, inputs.mode
    )
    if problems or again != wanted:  # pragma: no cover - guarded by the tests
        return MappingPlan(False, "That combination could not be written safely.")
    config: tuple[ConfigSet | ConfigTableArray, ...] = (
        ConfigTableArray("facegesture.switches", tuple(entries)),
    )
    note = ""
    # An eyes-closed binding with a blink-length hold would dictate on every blink. Raise the
    # shared hold in the same write -- never lower it: a longer value was somebody's choice.
    floor = eyes_closed_min_hold_frames(inputs.fps)
    if "eyes_closed" in wanted and inputs.min_hold_frames < floor:
        config += (ConfigSet("facegesture", "min_hold_frames", floor),)
        note = (
            f"The hold before any face switch counts was raised from "
            f"{_seconds(inputs.min_hold_frames, inputs.fps)} to {_seconds(floor, inputs.fps)}, "
            "so an ordinary blink does not start it."
        )
    spec = ActionSpec(
        id=f"map_{gesture}",
        label=f"Map {_gesture_label(gesture)} to {ACTION_LABELS[action]}",
        kind="adjust",
        enabled=True,
        help="Saved now; applies after `yazses restart`.",
        config=config,
        needs_restart=True,
    )
    return MappingPlan(True, "", spec, note)


# ------------------------------------------------------------------------------ the model


def build_panel(inputs: PanelInputs) -> PanelModel:
    """Everything the panel shows and every button it offers. Pure."""
    banner = overall_state(inputs)
    notes = [
        "Nothing here turns on by itself, and displaying this panel does not open the camera.",
    ]
    if not inputs.safety_configured and any(f.enabled for f in inputs.features):
        notes.append(
            "The global stop is off. Turn it on so one Pause reaches every hands-free input."
        )
    return PanelModel(
        banner=banner,
        actions=_actions(inputs, banner),
        dwell=_dwell(inputs),
        safety_toggle=_safety_toggle(inputs),
        features=_feature_rows(inputs),
        health=_health(inputs),
        mapping=_mapping(inputs),
        notes=tuple(notes),
    )


def render_text(model: PanelModel) -> list[str]:
    """The model as plain lines for the terminal and for a screen reader. Pure.

    The same words the window shows, in the same order, with the state word first on every
    row — so a terminal user and a window user read one panel.
    """
    out = [model.banner.headline]
    if model.banner.detail:
        out.append(model.banner.detail)
    out.append("")
    out.append("Actions (none needs a pointer position):")
    for spec in (*model.actions, *model.dwell):
        mark = "" if spec.enabled else f"  [unavailable: {spec.why_disabled}]"
        out.append(f"  {spec.label} — `{spec.cli}`{mark}")
    out.append("")
    out.append("Camera controls:")
    for row in model.features:
        out.append(f"  [{row.word}] {row.label}: {row.text}")
    out.append("")
    if model.health:
        out.append("Health:")
        for item in model.health:
            out.append(f"  [{item.word}] {item.label}: {item.text}")
            if item.remedy:
                out.append(f"      Next: {item.remedy}")
        out.append("")
    out.append("Face switch mapping:")
    for mrow in model.mapping.rows:
        out.append(
            f"  {mrow.gesture_label}: {mrow.action_label}" + (f" ({mrow.note})" if mrow.note else "")
        )
    for problem in model.mapping.problems:
        out.append(f"  ignored: {problem}")
    for note in model.notes:
        out.append(note)
    return out
