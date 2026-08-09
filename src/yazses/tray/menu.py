"""Pure menu + icon model for the system-tray UI.

The Qt layer (``platform/linux/tray.py``) is a thin shell around these pure functions:
given a daemon ``status`` dict and the local input-device list, they decide what the
click-menu should contain and what colour the tray icon should be. No Qt, no hardware,
so they unit-test directly.
"""
from __future__ import annotations

from dataclasses import dataclass

from yazses.audio.devices import InputDevice, resolve_input_device

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
    settings_label: str         # e.g. "Settings…" — opens the graphical settings window


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
