"""The hands-free preset: `[handsfree]` expanded into ordinary feature settings (pure).

ADR-v2-148 says hands-free mode is *a composition, not a second pipeline*, and Phase 6 of the
eye-control roadmap turns that into a test: ``[handsfree] enabled = true`` must resolve to exactly
the feature configs a user could have written by hand, and add no code path that a per-feature
config does not already reach. This module is how that is true by construction.

**What it does.** :func:`expand` reads the *raw* parsed config file and says which ordinary keys
(``[headpointer] enabled``, ``[gaze] route_dictation``, ``[handsfree_safety] enabled``, ...) the
preset sets, which of them the user already set themselves, and why. :func:`apply` writes the
preset's share into a copy of the raw file. The config loader runs both *before* it builds any
section, so everything downstream -- ``Config``, the daemon, ``doctor``, ``status``, the settings
panel -- sees an ordinary config and cannot tell a preset from a hand-written file. Nothing at
runtime reads ``cfg.handsfree``; a test pins that.

**Ownership: your key wins.** A key present in the user's file is theirs, and the preset leaves
it alone and says so in `yazses handsfree explain` -- the source of truth stays the feature
config (the spec's "no duplicate hidden settings"). The one exception is the *safety floor*
(``protected`` settings: the global stop, the destructive-command confirmation, and refusing a
destructive action on a fallback target). A user value that weakens one of those makes the preset
refuse *as a whole*, with the key and the fix named: half a preset -- a pointer with no global
stop -- is the exact hazard the ADR exists to prevent, and a silent override of the user's own
value would be the other mistake.

**Every value here is provisional.** No field evidence exists to tune any of them from
(``design/eye-control/GOVERNANCE.md``); they are starting values chosen to fail toward doing less
(a switch that needs a confidence floor, a global stop that is on, a destructive action that is
refused rather than guessed), and `explain` says so on every run. Gains, dead zone, speed caps and
the staleness window are deliberately *not* restated: they keep the defaults of the feature that
owns them, which are already documented as unmeasured.

Pure by contract (AGENTS.md rule 5): stdlib plus the config *schema* only -- no daemon, runtime,
camera, backend or I/O. A test pins that import list.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from yazses.config import HandsfreeConfig
from yazses.configcheck import build_section

__all__ = [
    "Expansion",
    "Resolved",
    "Setting",
    "apply",
    "expand",
    "render",
    "resolve_raw",
]

#: The role names, in the order `explain` prints them.
ROLE_SAFETY = "safety floor"
ROLE_CAMERA = "shared camera"
ROLE_GAZE = "gaze: target / context"
ROLE_POINTER = "head pointer: movement"
ROLE_DWELL = "dwell: commit"
ROLE_SWITCH = "face switch: hold to talk"
ROLE_CHORDS = "chords: recenter and stop"

#: Which feature (the toggle name `yazses features` uses) a section's ``enabled`` key is.
FEATURE_OF_SECTION: dict[str, str] = {
    "gaze": "gaze",
    "headpointer": "headpointer",
    "facegesture": "facegesture",
    "gesture": "gesture",
}

#: PROVISIONAL starting bindings for Gesture Chords. Canonical spelling (sorted tokens), because
#: the chord parser refuses two spellings of one chord. A deliberate brow-raise plus a double
#: nod/shake: the head gestures are the ones the chord defaults already ask to be deliberate.
CHORDS_RECENTER = "brow_raise+nod"
CHORDS_STOP = "brow_raise+shake"

#: PROVISIONAL: frames scoring below this presence confidence never count toward a face-switch
#: hold. Same number as Head-Pointer's own `min_confidence` so the two read one camera alike. It
#: can only make the switch fire *less*; it is not a measurement.
SWITCH_CONFIDENCE_FLOOR = 0.5

def stop_paths(components: HandsfreeConfig) -> tuple[str, ...]:
    """Where a stop can come from, for `explain`. The first two need neither a pointer nor a camera.

    That is what ADR-v2-148 requires of at least one path: it must still work when the camera is
    lost, which is the state the pointer is most likely to misbehave in.
    """
    out = [
        "`yazses handsfree pause` from any terminal or script (no pointer, no camera)",
        "the Pause button of the hands-free panel in the settings window (keyboard mnemonic P)",
    ]
    if components.chords:
        out.append(
            f"the chord {CHORDS_STOP.replace('+', ' + ')} (needs the camera, so it cannot help once "
            "the camera is lost)"
        )
    return tuple(out)


@dataclass(frozen=True)
class Setting:
    """One ordinary config key the preset would set."""

    section: str
    key: str
    value: Any
    role: str
    why: str
    #: Part of the safety floor: a contrary user value refuses the preset instead of winning.
    protected: bool = False


@dataclass(frozen=True)
class Resolved:
    """A :class:`Setting` after the user's own file has been consulted."""

    setting: Setting
    #: ``"preset"`` -- the preset's value is in effect; ``"yours"`` -- the user's value is.
    source: str
    #: The value that ends up in the resolved config.
    effective: Any

    @property
    def overridden(self) -> bool:
        """Did the user's value differ from what the preset would have set?"""
        return self.source == "yours" and self.effective != self.setting.value


@dataclass(frozen=True)
class Expansion:
    """The outcome of expanding ``[handsfree]``. Pure data; safe to print."""

    #: ``[handsfree] enabled`` as the file says it (or ``assume_enabled``).
    requested: bool
    #: Non-empty = the preset applies nothing, and this says why.
    refusal: str
    resolved: tuple[Resolved, ...]
    notes: tuple[str, ...]
    #: The components the user asked to compose, after defaults.
    components: HandsfreeConfig

    @property
    def active(self) -> bool:
        """Does the preset change anything? Requested, and not refused."""
        return self.requested and not self.refusal

    @property
    def features(self) -> tuple[str, ...]:
        """Toggle names of the camera-driven features the preset turns on."""
        out: list[str] = []
        for item in self.resolved:
            slug = FEATURE_OF_SECTION.get(item.setting.section)
            if slug and item.setting.key == "enabled" and item.setting.value is True:
                out.append(slug)
        return tuple(out)


# ------------------------------------------------------------------------- the table


def settings_for(components: HandsfreeConfig) -> tuple[Setting, ...]:
    """The ordinary keys the preset sets for these components, in print order. Pure.

    The whole definition of the preset lives in this one function; there is no other place a
    hands-free value is chosen.
    """
    out: list[Setting] = [
        Setting(
            "handsfree_safety", "enabled", True, ROLE_SAFETY,
            "one ACTIVE / PAUSED / FAULTED state every camera input obeys, and a stop path",
            protected=True,
        ),
        Setting(
            "cmdsafety", "enabled", True, ROLE_SAFETY,
            "a dangerous dictated command waits for a spoken confirm",
            protected=True,
        ),
    ]
    camera = components.gaze or components.pointer or components.switch or components.chords
    if camera:
        out.append(Setting(
            "perception", "enabled", True, ROLE_CAMERA,
            "one owner of the webcam, shared by every consumer below",
        ))
    if components.gaze:
        out += [
            Setting("gaze", "enabled", True, ROLE_GAZE, "look at a window to choose where words land"),
            Setting("gaze", "route_dictation", True, ROLE_GAZE, "dictation follows the looked-at window"),
            Setting("gaze", "deixis", True, ROLE_GAZE, '"close this" / "focus that" act on the looked-at window'),
            Setting(
                "gaze", "confirm_destructive", True, ROLE_GAZE,
                "a gaze-routed close asks first (existing confirmation policy)", protected=True,
            ),
            Setting(
                "gaze", "refuse_destructive_fallback", True, ROLE_GAZE,
                "if gaze cannot pick the window, a destructive action is refused with feedback, "
                "never run on the focused window", protected=True,
            ),
        ]
    if components.pointer:
        out.append(Setting(
            "headpointer", "enabled", True, ROLE_POINTER,
            "the head moves the cursor; gains and speed caps keep their own provisional defaults",
        ))
        if components.dwell:
            out.append(Setting(
                "headpointer", "dwell_enabled", True, ROLE_DWELL,
                "hold still to click -- the only commit wired today; clicks only while the overlay "
                "is shown",
            ))
    if components.switch:
        out += [
            Setting("facegesture", "enabled", True, ROLE_SWITCH,
                    "hold a jaw-open to dictate instead of a key (the switch's own default binding)"),
            Setting("facegesture", "use_baseline", True, ROLE_SWITCH,
                    "score against your own resting face when `yazses facegesture calibrate` was run; "
                    "otherwise the plain threshold, with a log line saying so"),
            Setting("facegesture", "confidence_floor", SWITCH_CONFIDENCE_FLOOR, ROLE_SWITCH,
                    "provisional: low-confidence frames never count toward a hold"),
        ]
    if components.chords:
        chords = {CHORDS_STOP: "pause_pointer"}
        if components.pointer:
            chords[CHORDS_RECENTER] = "recenter"
        out += [
            Setting("gesture", "enabled", True, ROLE_CHORDS, "chords are the camera-side stop and recenter"),
            Setting("gesture", "chords", chords, ROLE_CHORDS,
                    "provisional bindings: a deliberate brow-raise plus a nod (recenter) or shake (stop)"),
        ]
    return tuple(out)


# ------------------------------------------------------------------------- expansion


def _section(raw: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    value = raw.get(name)
    return value if isinstance(value, Mapping) else None


def expand(raw: Mapping[str, Any], *, assume_enabled: bool = False) -> Expansion:
    """Expand ``[handsfree]`` against the raw parsed config file. Pure; never raises on input.

    ``assume_enabled`` answers "what *would* ``enabled = true`` do to this file" for `explain`
    and `enable`, without the file saying so.
    """
    hf_raw = raw.get("handsfree") if isinstance(raw, Mapping) else None
    components = build_section(HandsfreeConfig, dict(hf_raw) if isinstance(hf_raw, Mapping) else {},
                               "handsfree", [])
    requested = bool(components.enabled) or assume_enabled
    resolved: list[Resolved] = []
    notes: list[str] = []
    refusals: list[str] = []
    for setting in settings_for(components):
        table = _section(raw, setting.section)
        if setting.section in raw and table is None:
            notes.append(
                f"[{setting.section}] is not a table in your file, so the preset left "
                f"[{setting.section}] {setting.key} alone."
            )
            continue
        if table is not None and setting.key in table:
            theirs = table[setting.key]
            resolved.append(Resolved(setting, "yours", theirs))
            if setting.protected and theirs != setting.value:
                refusals.append(
                    f"[{setting.section}] {setting.key} = {_toml(theirs)} in your config weakens the "
                    f"hands-free safety floor ({setting.why}). Set it to {_toml(setting.value)} or "
                    f"remove it, or set [handsfree] enabled = false."
                )
            continue
        resolved.append(Resolved(setting, "preset", copy.deepcopy(setting.value)))
    notes += _notes(components, raw)
    return Expansion(
        requested=requested,
        refusal=" ".join(refusals),
        resolved=tuple(resolved),
        notes=tuple(notes),
        components=components,
    )


def _notes(components: HandsfreeConfig, raw: Mapping[str, Any]) -> list[str]:
    """Honest limits of what the preset composes. Static facts plus two derived from the file."""
    out: list[str] = [
        "PROVISIONAL -- every value the preset supplies is an unmeasured starting value; no field "
        "evidence exists to tune them from (design/eye-control/GOVERNANCE.md).",
        "Not composed: the Voice Mouse Grid ([mousegrid]) is designed but not wired into this build, "
        "so the precision fallback is not part of the preset; the face-switch actions select / "
        "confirm / cancel have no daemon handler yet, so the commit is dwell-click only.",
    ]
    headpointer = _section(raw, "headpointer") or {}
    dwell_on = components.pointer and components.dwell and headpointer.get("dwell_enabled", True) is not False
    if dwell_on:
        overlay = _section(raw, "overlay")
        if overlay is None or overlay.get("enabled") is not True:
            out.append(
                "Dwell-click only clicks while the overlay that draws its progress ring is shown: "
                "set [overlay] enabled = true (it is opt-in; on some Wayland sessions it takes keyboard focus). "
                "Without it the pointer moves and never clicks."
            )
    if components.gaze:
        out.append(
            'If gaze cannot pick a window, "close this" is refused with a notification and nothing '
            "is closed; it is never run on the focused window instead."
        )
    return out


def apply(raw: Mapping[str, Any], expansion: Expansion) -> dict[str, Any]:
    """A copy of ``raw`` with the preset's share written in. Pure.

    Identity (a plain copy) when the preset is off or was refused. A section the user wrote is
    extended, never replaced; a key the user wrote is never touched.
    """
    out: dict[str, Any] = {k: copy.deepcopy(v) for k, v in raw.items()}
    if not expansion.active:
        return out
    for item in expansion.resolved:
        if item.source != "preset":
            continue
        name = item.setting.section
        table = out.get(name)
        if table is None:
            table = {}
            out[name] = table
        if isinstance(table, dict):
            table[item.setting.key] = copy.deepcopy(item.effective)
    return out


def resolve_raw(raw: Mapping[str, Any]) -> tuple[dict[str, Any], Expansion]:
    """``(raw with the preset applied, the expansion)`` -- the one call the loader makes."""
    expansion = expand(raw)
    return apply(raw, expansion), expansion


# ------------------------------------------------------------------------- explain


def _toml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Mapping):
        return "{ " + ", ".join(f'"{k}" = "{v}"' for k, v in value.items()) + " }"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def render(expansion: Expansion, *, enabled_in_file: bool) -> list[str]:
    """The resolved per-feature config as plain lines, with where each value came from. Pure.

    Prints names, values and provenance only -- no sample, frame or position. ``explain`` never
    applies anything; this is all it prints.
    """
    head = (
        "Hands-free preset: ON in your config."
        if enabled_in_file
        else "Hands-free preset: OFF in your config. This is what `yazses handsfree enable` would set."
    )
    lines = [head]
    if expansion.refusal:
        lines.append(f"REFUSED -- nothing below is applied. {expansion.refusal}")
    components = expansion.components
    chosen = ", ".join(
        name for name in ("gaze", "pointer", "dwell", "switch", "chords") if getattr(components, name)
    )
    lines.append(f"Roles composed: {chosen or 'none'}  (switch any off under [handsfree])")
    lines.append("")
    role = ""
    for item in expansion.resolved:
        if item.setting.role != role:
            role = item.setting.role
            lines.append(f"# {role}")
        s = item.setting
        if item.source == "preset":
            tag = "preset"
        elif item.overridden:
            tag = f"YOURS (preset would set {_toml(s.value)})"
        else:
            tag = "yours (same as preset)"
        mark = "  [safety floor]" if s.protected else ""
        lines.append(f"[{s.section}] {s.key} = {_toml(item.effective)}    <- {tag}{mark}")
        lines.append(f"    {s.why}")
    lines.append("")
    lines.append("Ways to stop (none needs you to aim the pointer):")
    lines += [f"  - {p}" for p in stop_paths(components)]
    lines.append("")
    lines += [f"Note: {n}" for n in expansion.notes]
    return lines
