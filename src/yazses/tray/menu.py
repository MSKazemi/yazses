"""Pure menu + icon model for the system-tray UI.

The Qt layer (``platform/linux/tray.py``) is a thin shell around these pure functions:
given a daemon ``status`` dict and the local input-device list, they decide what the
click-menu should contain and what colour the tray icon should be. No Qt, no hardware,
so they unit-test directly.
"""
from __future__ import annotations

from dataclasses import dataclass

from yazses.audio.devices import InputDevice, resolve_input_device

# Icon colours per daemon state (hex). A live silent-streak overrides these with a
# warning colour so the top bar flags "we're not hearing you" at a glance.
_STATE_COLOR = {
    "loading": "#9aa0a6",       # grey
    "idle": "#1a73e8",          # blue
    "recording": "#ea4335",     # red
    "transcribing": "#fbbc04",  # amber
    "injecting": "#34a853",     # green
    "readback": "#a142f4",      # purple
    "paused": "#9aa0a6",
    "error": "#ff6d00",         # orange
    "remote_setup": "#1a73e8",
    "remote_active": "#34a853",
    "enrolling": "#1a73e8",
    "meeting": "#a142f4",
}
_WARNING_COLOR = "#ff6d00"      # orange — silent-streak / error
_DEFAULT_COLOR = "#1a73e8"


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
    return TrayMenuModel(header=header, mic_line=mic_line, warning=warning, devices=items)


def icon_spec(status: dict) -> tuple[str, str]:
    """Return ``(hex_color, tooltip)`` for the tray icon given a status dict.

    A live silent-streak forces the warning colour regardless of state, so a mic that
    stopped being heard is visible in the top bar without opening the menu.
    """
    state = str(status.get("state") or "idle")
    streak = int(status.get("silent_streak") or 0)
    if streak or state == "error":
        color = _WARNING_COLOR
    else:
        color = _STATE_COLOR.get(state, _DEFAULT_COLOR)

    mic = status.get("input_device") or "default"
    hotkey = status.get("hotkey") or "?"
    tooltip = f"YazSes — {state}\nMic: {mic}\nHold {hotkey} to dictate"
    if streak:
        tooltip += f"\n⚠ {streak} silent clip(s) in a row"
    return color, tooltip
