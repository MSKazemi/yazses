"""Pure menu + icon model for the system-tray UI.

The Qt layer (``platform/linux/tray.py``) is a thin shell around these pure functions:
given a daemon ``status`` dict and the local input-device list, they decide what the
click-menu should contain and what colour the tray icon should be. No Qt, no hardware,
so they unit-test directly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from yazses.audio.devices import InputDevice, resolve_input_device

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yazses.platform.base import TrayModel

# Three-colour scheme: GREEN while recording your voice (you're holding the key and
# speaking, through the brief transcribe/inject that finishes that dictation), BLUE for
# the normal ready/idle state, RED for a problem (error or a live silent-streak). So a
# glance at the top bar says recording vs ready vs needs-attention.
_GREEN = "#34a853"      # recording — holding the key and speaking (into a text field)
_YELLOW = "#fbbc04"     # recording but NO text field focused (would type nowhere)
_PURPLE = "#9c27b0"     # command mode — holding the command key (a command, not dictation)
_BLUE = "#1a73e8"       # normal / ready / idle
_RED = "#e53935"        # problem — error or silent-streak
# Mirrors AudioConfig.silent_streak_threshold; used when status doesn't carry it.
_DEFAULT_SILENT_STREAK_LIMIT = 3
# Label for the menu entry that opens the graphical settings window (`yazses settings`).
SETTINGS_LABEL = "Settings…"
# The three entries that answer the questions a user has *at the icon*: what am I
# running, where do I get help, is there a newer version. One constant each, imported by
# all three trays, so the same menu cannot come to mean different things per OS (#63).
ABOUT_LABEL = "About YazSes"
HELP_LABEL = "Help"
DOCS_LABEL = "Documentation"
TROUBLESHOOTING_LABEL = "Troubleshooting"
REPORT_BUG_LABEL = "Report a bug…"
UPDATE_LABEL = "Check for updates…"
# Meeting Mode's two live actions. Meeting Mode is the one capability with no key to
# hold — it runs hands-free for an hour — so until now the only way to begin or end one
# was a terminal, which is exactly what you do not have open in a meeting.
MEETING_START_LABEL = "Start meeting"
MEETING_STOP_LABEL = "Stop meeting"
# Actively capturing/handling your dictation → green. Everything else that is not a
# problem → blue (normal). Meeting Mode also captures audio, so it is green too.
_RECORDING_STATES = frozenset(
    {
        "recording",
        "transcribing",
        "injecting",
        "meeting",
    }
)


@dataclass(frozen=True)
class DeviceItem:
    """One entry in the Microphone submenu (a radio choice)."""

    label: str      # what to show
    device: str     # the substring to pin ("" = follow the OS default)
    checked: bool   # currently the active mic


@dataclass(frozen=True)
class TrayMenuModel:
    """Everything the tray needs to render its menu, derived purely from status."""

    header: str                 # e.g. "YazSes — idle"
    mic_line: str               # e.g. "Mic: default"
    warning: str | None         # e.g. "⚠ 2 silent clips in a row" or None
    devices: list[DeviceItem]   # "Follow OS default" first, then each input device
    # "Settings…" — opens the graphical settings window. Defaulted so a caller that
    # builds the model directly (a platform tray, a test) keeps working.
    settings_label: str = SETTINGS_LABEL


def build_menu_model(
    status: dict, devices: list[InputDevice], pinned: str
) -> TrayMenuModel:
    """Compose the tray menu model from a daemon ``status`` dict + device list.

    ``pinned`` is the configured ``[audio] device`` (empty = follow OS default). The
    device whose resolution matches the pin is checked; when nothing is pinned the
    "Follow OS default" entry is checked instead.
    """
    state = str(status.get("state") or "idle")
    header = f"YazSes — {state}"

    input_device = status.get("input_device") or "default"
    mic_line = f"Mic: {input_device}"

    streak = int(status.get("silent_streak") or 0)
    warning = (
        f"⚠ {streak} silent clip{'s' if streak != 1 else ''} in a row" if streak else None
    )

    pinned = (pinned or "").strip()
    resolved_index = resolve_input_device(pinned, devices) if pinned else None
    items: list[DeviceItem] = [
        DeviceItem(label="Follow OS default", device="", checked=not pinned)
    ]
    for dev in devices:
        items.append(
            DeviceItem(
                label=dev.name + (" (OS default)" if dev.is_default else ""),
                device=dev.name,
                checked=(resolved_index is not None and dev.index == resolved_index),
            )
        )
    return TrayMenuModel(
        header=header,
        mic_line=mic_line,
        warning=warning,
        devices=items,
        settings_label=SETTINGS_LABEL,
    )


@dataclass(frozen=True)
class MeetingEntry:
    """One Meeting Mode menu entry, and whether clicking it can do anything.

    ``reason`` is never None when ``enabled`` is False. A greyed-out entry with no
    explanation is worse than no entry at all: the user is left deciding between "this
    is broken" and "I am not allowed", and the answer is usually neither.
    """

    label: str
    action: str          # the IPC method a click invokes
    enabled: bool
    reason: str | None = None


# The daemon's own guard in `_handle_meeting_start`: a meeting may only begin from a
# resting state, because starting one mid-dictation would take the microphone away from
# a burst in progress.
_MEETING_START_STATES = frozenset({"idle", "paused"})


def meeting_entries(status: dict) -> list[MeetingEntry]:
    """The Start/Stop meeting entries for *status*. Pure.

    Both entries are always returned, in a fixed order, because two of the three trays
    build their menu once at startup and cannot swap a label later. So the shape has to
    be the same every tick, and it is the *enabled* flag that moves.

    **The daemon decides; this predicts.** Every rule below mirrors one the daemon
    enforces in `_handle_meeting_start`, and a prediction that disagrees with it is a
    bug in this function, not a licence for the tray to act. That is why a click still
    sends the IPC call and still shows whatever ``reason`` comes back: this layer exists
    to grey out a doomed click and say why, not to become a second authority on when a
    meeting may run.
    """
    state = str(status.get("state") or "idle")
    active = bool(status.get("meeting_active")) or state == "meeting"
    finalizing = bool(status.get("meeting_finalizing"))
    # Absent on an older daemon that predates the field. Treating that as "off" would
    # grey the entry out on a daemon where Meeting Mode works perfectly well, so the
    # benefit of the doubt goes to enabled and the daemon refuses if it is wrong.
    enabled_raw = status.get("meeting_enabled")
    feature_on = True if enabled_raw is None else bool(enabled_raw)
    # `ready` is likewise absent from a bare model-derived status; only an explicit
    # False means "still loading".
    loading = status.get("ready") is False

    def _blocked() -> str | None:
        """A reason that stops *both* actions, or None."""
        if not feature_on:
            return (
                "Meeting Mode is off — turn it on in Settings, then restart YazSes."
            )
        if loading:
            return "YazSes is still starting up."
        if finalizing:
            return "Still finishing the last meeting — transcribing and writing it up."
        return None

    blocked = _blocked()
    if blocked is not None:
        return [
            MeetingEntry(MEETING_START_LABEL, "meeting_start", False, blocked),
            MeetingEntry(MEETING_STOP_LABEL, "meeting_stop", False, blocked),
        ]

    if active:
        return [
            MeetingEntry(
                MEETING_START_LABEL, "meeting_start", False,
                "A meeting is already running.",
            ),
            MeetingEntry(MEETING_STOP_LABEL, "meeting_stop", True),
        ]

    start_reason = (
        None if state in _MEETING_START_STATES
        else f"YazSes is busy ({state}) — try again in a moment."
    )
    return [
        MeetingEntry(
            MEETING_START_LABEL, "meeting_start", start_reason is None, start_reason
        ),
        MeetingEntry(
            MEETING_STOP_LABEL, "meeting_stop", False, "No meeting is running."
        ),
    ]


def _silent_streak_limit(status: dict) -> int:
    """How many consecutive silent clips make the icon red.

    The daemon only treats a silent streak as trouble once it reaches
    ``[audio] silent_streak_threshold`` (default 3) — one discarded clip is ordinary:
    the hotkey gets brushed, or a burst is released before speaking. The icon used to
    go red at the first one, so a single stray press left a red "something is broken"
    badge over a daemon that was working, until the next successful dictation cleared
    it. Colour on the daemon's own rule instead.

    Falls back to the config default when the key is absent, so an older daemon still
    gets sane behaviour rather than the old alarm-at-one.
    """
    raw = status.get("silent_streak_threshold")
    try:
        limit = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _DEFAULT_SILENT_STREAK_LIMIT
    return limit if limit > 0 else _DEFAULT_SILENT_STREAK_LIMIT


def glyph_for(badge_hex: str) -> str:
    """The mark colour that is actually legible on *badge_hex* — black or white.

    The glyph was white on every state colour. Measured with the contrast maths
    already in `settingsui/theme.py` — the only such maths in the codebase, and
    never applied anywhere near the tray — white scores:

        yellow 1.71:1 · green 3.06:1 · red 4.23:1 · blue 4.51:1 · purple 6.30:1

    WCAG AA asks 4.5:1, so three of the five failed. The worst is **yellow**, which
    is the badge meaning "recording, but there is nowhere to type" — the state a
    user most needs to notice, wearing the least readable mark of the set. An icon
    that says "your words are going nowhere" and cannot be read is not doing the
    one job it exists for.

    Black or white rather than a computed tint: at 16 px the mark is a few hundred
    pixels of stroke, and a mid-tone loses to the badge whatever the maths says.
    Falls back to white on an unparseable colour rather than raising — the paint
    path swallows exceptions, so an error here would mean no icon at all.
    """
    from yazses.settingsui.theme import contrast_ratio

    text = (badge_hex or "").strip().lstrip("#")
    if len(text) != 6:
        return "#ffffff"
    try:
        badge = tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#ffffff"

    white = contrast_ratio((255, 255, 255), badge)  # type: ignore[arg-type]
    black = contrast_ratio((0, 0, 0), badge)  # type: ignore[arg-type]
    return "#ffffff" if white >= black else "#000000"


def icon_spec(status: dict) -> tuple[str, str]:
    """Return ``(hex_color, tooltip)`` for the tray icon given a status dict.

    Purple while holding the command key (command mode — a command, not dictation),
    green while dictating into a text field, yellow while dictating with NO text field
    focused (your words would go nowhere — saved to the clipboard instead), blue for the
    normal ready/idle state, red for a problem (error or a live silent-streak).
    """
    state = str(status.get("state") or "idle")
    streak = int(status.get("silent_streak") or 0)
    target_ok = status.get("target_ok")
    command_mode = bool(status.get("command_mode"))
    if state in _RECORDING_STATES and command_mode:
        color = _PURPLE  # command mode — holding the command key
    elif streak >= _silent_streak_limit(status) or state == "error":
        color = _RED  # problem
    elif state in _RECORDING_STATES:
        # Dictation: green normally, yellow when we're confident there's no text target.
        color = _YELLOW if target_ok is False else _GREEN
    else:
        color = _BLUE  # normal / ready / idle

    mic = status.get("input_device") or "default"
    hotkey = status.get("hotkey") or "?"
    label = "command mode" if (state in _RECORDING_STATES and command_mode) else state
    tooltip = f"YazSes — {label}\nMic: {mic}\nHold {hotkey} to dictate"
    if state in _RECORDING_STATES and command_mode:
        tooltip += "\n⌘ command mode — parsing a command, not typing"
    if streak:
        tooltip += f"\n⚠ {streak} silent clip(s) in a row"
    if state in _RECORDING_STATES and not command_mode and target_ok is False:
        tooltip += "\n⚠ no text field focused — will save to clipboard"
    return color, tooltip


def status_from_model(model: TrayModel) -> dict:
    """Flatten a ``TrayModel`` into the daemon-shaped status dict ``icon_spec`` reads.

    Every platform tray receives a ``TrayModel`` but the pure policy above is
    written against the daemon's own status dict, so each backend has to bridge
    the two. Linux did it inline and Windows did not do it at all — which is how
    the Windows tray ended up with a private seven-colour table, no command-mode
    purple, no no-text-target yellow, and five ``TrayState`` members that
    silently rendered as idle blue. One shared bridge, so they cannot diverge.
    """
    from yazses.platform.base import TrayState as _TrayState

    state = model.state
    return {
        "state": state.value if isinstance(state, _TrayState) else state,
        "hotkey": model.hotkey,
        "model": model.model,
        "input_device": model.input_device,
        "silent_streak": model.silent_streak,
        "target_ok": model.target_ok,
        "command_mode": model.command_mode,
        # The level ring reads these two. They belong in the shared bridge rather
        # than in one backend's inline copy: the Linux tray built this dict by hand
        # and included them, Windows built a different dict and did not, and that
        # asymmetry is the same one that gave Windows a private colour table. A
        # backend that cannot draw a ring simply ignores them.
        "audio_level": model.audio_level,
        "vad_threshold": model.vad_threshold,
        # Meeting Mode's Start/Stop entries read these. Same reasoning as the two
        # above: they belong in the one shared bridge, so a tray cannot end up with a
        # menu entry that is permanently greyed out because its own hand-built dict
        # forgot a key.
        "meeting_enabled": model.meeting_enabled,
        "meeting_active": model.meeting_active,
        "meeting_finalizing": model.meeting_finalizing,
    }


# --------------------------------------------------------------------------- #
# Live input level — the one thing the five colours cannot say
# --------------------------------------------------------------------------- #
# Green means "the daemon is recording". It does not mean "your microphone is
# hearing you", and those come apart exactly when it matters: a muted mic, a USB-C
# monitor that stole capture, a VAD threshold set above the user's voice. The
# symptom is the most common one this project has — `Silent audio -- discarding`
# has its own troubleshooting page — and today the icon looks identical throughout.
# You speak a whole sentence, the badge is green, and nothing is typed.
#
# So the badge carries a level ring while recording. The daemon already publishes
# both numbers it needs (`audio_level`, `vad_threshold`) for the overlay, so this
# costs no daemon change and no extra IPC.
#
# The design decision that makes it readable: **the gate is anchored at a fixed
# position on the ring** rather than the ring being a linear map of the raw level.
# `audio_level` is mean(|samples|) — a number whose useful range depends on the mic,
# the room and the threshold. Drawn linearly, a quiet setup would sit invisibly near
# zero and a loud one would peg. Anchored, "the ring passed the notch" means
# "this will be transcribed" on every machine, which is the only question being asked.
_GATE_AT = 0.35     # the VAD threshold sits here on a 0..1 ring
_RING_MIN = 0.04    # a floor, so a live-but-silent mic still reads as "listening"


@dataclass(frozen=True)
class LevelRing:
    """How to draw the input-level ring around the badge.

    ``fraction`` is 0..1 of a full sweep. ``above_gate`` is whether the current level
    would pass the silence gate — i.e. whether speaking right now produces text.
    ``show`` is false whenever there is nothing honest to draw.
    """

    fraction: float
    above_gate: bool
    show: bool

    @property
    def gate_fraction(self) -> float:
        """Where to draw the notch that marks the threshold."""
        return _GATE_AT


#: Dynamic range shown above the gate, as a multiple of it. 100x is 40 dB, the
#: conventional span of an audio level meter.
_RING_RANGE = 100.0


def level_ring(status: dict) -> LevelRing:
    """The level ring for *status*. Pure.

    Hidden unless recording: an idle badge with a ring would imply YazSes is
    listening when it is not, which is the opposite of what this project promises.
    Hidden too when the threshold is missing or non-positive, because the gate
    position would be meaningless and a ring with no reference point is decoration.
    """
    state = str(status.get("state") or "idle")
    if state not in _RECORDING_STATES:
        return LevelRing(0.0, False, False)

    try:
        level = float(status.get("audio_level") or 0.0)
        threshold = float(status.get("vad_threshold") or 0.0)
    except (TypeError, ValueError):
        return LevelRing(0.0, False, False)
    if threshold <= 0 or level < 0:
        return LevelRing(0.0, False, False)

    ratio = level / threshold
    if ratio <= 1.0:
        # Below the gate: the sub-gate range maps onto the arc before the notch, so
        # a user can see themselves approaching it rather than only that they failed.
        fraction = _GATE_AT * ratio
    else:
        # Above it: logarithmic, like every other level meter, because the ratio is not
        # scale-free across users. A well-calibrated gate sits just under the voice
        # (ratio ~2-4); a gate set too low puts the same voice at 40x. Any fixed linear
        # span is therefore wrong for somebody.
        #
        # It was linear with full scale at 4x the threshold, and "ordinary speech fills
        # a useful amount of ring" did not survive contact with real speech: measured
        # over 1617 recorded bursts, the ring pegged on 44% of them at the DEFAULT
        # threshold and 97% at a threshold set low. A meter that reads full for half of
        # normal speech carries about one bit.
        #
        # _RING_RANGE is 100x, the conventional 40 dB meter span. Over the same bursts
        # that is 0% pegged at the default gate and 0% at 0.004, while the spread of
        # readings stays near-constant across every threshold -- which is the property
        # the linear map lacked. A gate set 40x below the voice still reads near full,
        # and should: that is a real fault the ring is entitled to show.
        over = min(math.log(ratio) / math.log(_RING_RANGE), 1.0)
        fraction = _GATE_AT + (1.0 - _GATE_AT) * over
    return LevelRing(max(_RING_MIN, min(1.0, fraction)), ratio > 1.0, True)
