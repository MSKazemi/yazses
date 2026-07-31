"""Audio input-device enumeration and name-based resolution.

The recorder normally follows PortAudio's *current default* input device (opening
``sd.InputStream`` with no ``device=``). That silently breaks when the OS re-picks a
different default — e.g. plugging in a USB-C monitor that exposes an audio endpoint —
because capture switches to a wrong/quiet source and every clip is gated as silence.

This module lets a mic be pinned by **name substring** (``[audio] device``) and resolved
freshly at each recording, so a hotplug that shifts device *indices* can't break the pin.
The pure functions take an injected device list so tests never touch real hardware.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class InputDevice:
    """One capture-capable audio device."""

    index: int
    name: str
    channels: int
    is_default: bool = False


def _default_input_index() -> int | None:
    """PortAudio's current default *input* device index, or None. Best-effort."""
    try:
        import sounddevice as sd

        dev = sd.default.device
        # sd.default.device is (input_idx, output_idx); -1 means "unset".
        idx = dev[0] if isinstance(dev, (list, tuple)) else dev
        idx = int(idx)
        return idx if idx >= 0 else None
    except Exception:  # pragma: no cover - depends on the audio backend
        return None


def list_input_devices(
    query=None, default_index: int | None = None, default_name: str | None = None
) -> list[InputDevice]:
    """Return every capture-capable device.

    ``query`` defaults to ``sd.query_devices`` and must return the full PortAudio
    device list (a sequence of dicts). The OS default input is marked by ``default_index``
    when available, else by ``default_name`` (some ALSA setups leave the index unset but
    expose a named ``"default"`` device). Both default hints are read from PortAudio when
    omitted; all three are injectable so tests run without an audio backend.
    """
    if query is None:
        import sounddevice as sd

        query = sd.query_devices
    if default_index is None:
        default_index = _default_input_index()
    if default_index is None and default_name is None:
        default_name = current_default_input_name()

    try:
        raw = query()
    except Exception as exc:  # pragma: no cover - hardware/backend dependent
        log.debug("query_devices failed: %s", exc)
        return []

    dname = (default_name or "").strip().lower()
    devices: list[InputDevice] = []
    for idx, info in enumerate(raw):
        # PortAudio indexes devices by their position in the full list; that index
        # is what ``sd.InputStream(device=...)`` expects, so preserve it.
        if int(info.get("max_input_channels", 0)) > 0:
            name = str(info.get("name", f"device {idx}"))
            is_default = (idx == default_index) or (
                default_index is None and bool(dname) and name.lower() == dname
            )
            devices.append(
                InputDevice(
                    index=idx,
                    name=name,
                    channels=int(info.get("max_input_channels", 0)),
                    is_default=is_default,
                )
            )
    return devices


def default_input_name(devices: list[InputDevice]) -> str | None:
    """Name of the default input device among ``devices``, or None."""
    for dev in devices:
        if dev.is_default:
            return dev.name
    return None


def current_default_input_name() -> str | None:
    """The OS default input device's name *right now*, or None. Best-effort.

    Used by the device-change monitor. Reads live state from PortAudio rather than a
    cached list, so it reflects a default that flipped since the daemon started.
    """
    try:
        import sounddevice as sd

        info = sd.query_devices(kind="input")
    except Exception:  # pragma: no cover - hardware/backend dependent
        return None
    if not info:
        return None
    name = info.get("name") if isinstance(info, dict) else None
    return str(name) if name else None


def resolve_input_device(name: str, devices: list[InputDevice]) -> int | None:
    """Resolve a pinned device ``name`` to a PortAudio index against ``devices``.

    Matching is case-insensitive: an exact name wins, otherwise the first
    substring match (in device order). Returns ``None`` when ``name`` is blank or
    nothing matches — the caller then falls back to the OS default device.
    """
    needle = (name or "").strip().lower()
    if not needle:
        return None
    for dev in devices:  # exact match first
        if dev.name.lower() == needle:
            return dev.index
    for dev in devices:  # then substring
        if needle in dev.name.lower():
            return dev.index
    return None


def reinit_portaudio() -> None:
    """Re-initialise PortAudio so hotplugged devices become visible.

    ``sd.query_devices`` caches the device list at initialisation, so a mic added
    after the daemon started is otherwise invisible. Terminating and re-initialising
    refreshes it. Best-effort and never raises; must not be called while a stream is
    open (the device-change monitor only polls when the daemon is idle).
    """
    try:
        import sounddevice as sd

        sd._terminate()
        sd._initialize()
    except Exception as exc:  # pragma: no cover - hardware/backend dependent
        log.debug("PortAudio reinit failed: %s", exc)
