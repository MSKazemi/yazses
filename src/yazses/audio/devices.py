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


def match_input_devices(name: str, devices: list[InputDevice]) -> list[InputDevice]:
    """Every device ``name`` selects, in the order :func:`resolve_input_device` sees them.

    Split out from the resolver so that "which device is this?" and "is that the only
    one?" are answered by the same code. The daemon only ever needs the first match, but
    `yazses audio use` has to be able to say *how many* there are: a name matching more
    than one device resolves by PortAudio enumeration order, which is precisely what a
    hotplug or a reboot reshuffles — so an ambiguous pin keeps the failure mode that
    pinning exists to remove, while looking like it fixed it.

    Case-insensitive, exact matches first. An exact match is never ambiguous with the
    substrings it happens to sit inside (``default`` inside ``sysdefault``).
    """
    needle = (name or "").strip().lower()
    if not needle:
        return []
    exact = [d for d in devices if d.name.lower() == needle]
    if exact:
        return exact
    return [d for d in devices if needle in d.name.lower()]


def resolve_input_device(name: str, devices: list[InputDevice]) -> int | None:
    """Resolve a pinned device ``name`` to a PortAudio index against ``devices``.

    Matching is case-insensitive: an exact name wins, otherwise the first
    substring match (in device order). Returns ``None`` when ``name`` is blank or
    nothing matches — the caller then falls back to the OS default device.
    """
    matches = match_input_devices(name, devices)
    return matches[0].index if matches else None


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


#: Names PortAudio reports for a *route* rather than a microphone. On ALSA and
#: PipeWire these are virtual entries that forward to whichever device is current,
#: so the name stays the same when the hardware behind it changes.
_ROUTING_ALIASES = frozenset({"default", "pipewire", "pulse", "sysdefault"})


def is_routing_alias(name: str | None) -> bool:
    """True when *name* is a route rather than a microphone.

    This is why the device-change watcher cannot see a switch on a typical Linux
    desktop: it detects a change by comparing this name over time, and against an
    alias it compares ``default`` with ``default`` for ever. Reading through the
    alias needs a PipeWire or PulseAudio client library, which is a dependency this
    project does not take on for one diagnostic — so the limitation is named where
    a user looks instead of being silently absent.

    The streak-based half of the guard is unaffected: it counts outcomes, not names.
    """
    return (name or "").strip().lower() in _ROUTING_ALIASES


def alias_pin_advice(behind_name, devices) -> str:
    """How to actually pin the microphone hiding behind a routing alias. Pure.

    `yazses audio status` resolves the alias through wpctl and prints the real device --
    "Raptor Lake-P/U/H cAVS Digital Microphone" -- directly above "Pin a real one to be
    sure: yazses audio use <name>". That reads as an instruction to type the name it just
    showed you, and on this machine that name **cannot be pinned**: it comes from the
    sound server's graph, while `audio use` matches against PortAudio's capture list,
    which offers only `sof-hda-dsp: - (hw:0,0)`, `pipewire`, `sysdefault` and `default`.

    `audio use` warns on a name it cannot match and then pins it anyway -- deliberately,
    so a hotplugged device can be pinned before it appears. The combination is the
    problem: the pin is accepted, never resolves, capture silently falls back to the
    alias, and the user believes they fixed the exact thing the pin exists to prevent.

    So the advice is derived from whether the name resolves, rather than assumed.

    ``devices`` is the PortAudio input list; ``behind_name`` may be None when wpctl is
    absent, which is ordinary rather than an error.
    """
    selectable = [d.name for d in devices if not is_routing_alias(d.name)]
    if behind_name:
        # A name that resolves is not automatically worth pinning: on a PipeWire box
        # `default` can sit behind `pipewire`, which is another alias. Offering it would
        # reproduce the very failure this advice exists to prevent, one layer down.
        if is_routing_alias(behind_name):
            return "Pin one of the hardware names from `yazses audio devices`."
        if resolve_input_device(behind_name, devices) is not None:
            return f'Pin it with:  yazses audio use "{behind_name}"'
        return (
            "That name comes from the sound server, not from the capture list, so "
            "`yazses audio use` cannot select it.\n                 Pin a hardware name "
            "from `yazses audio devices` instead."
        )
    if not selectable:
        return (
            "Every input this machine offers is a routing alias, so there is nothing to "
            "pin — capture will follow whatever the OS points at."
        )
    return "Pin one of the names from `yazses audio devices`."


def parse_wpctl_default_source(text: str):
    """``(name, volume)`` of the starred source in ``wpctl status`` output, or None.

    Pure, so the parsing is tested without PipeWire. Only the ``Sources:`` block is
    considered -- ``Sinks:`` has the same row shape and its own starred default, and
    reporting a speaker as the microphone would be worse than saying nothing.

    Returns None when nothing is marked default: which source is current is then
    genuinely unknown, and guessing is how a diagnostic starts lying.
    """
    import re

    in_sources = False
    for line in (text or "").splitlines():
        stripped = line.strip(" \u2502\u251c\u2514\u2500")
        if stripped.endswith(":"):
            in_sources = stripped.rstrip(":").strip().lower() == "sources"
            continue
        if not in_sources or "*" not in line:
            continue
        m = re.search(r"\*\s*\d+\.\s*(.+?)\s*\[vol:\s*([0-9.]+)", line)
        if m:
            return (m.group(1).strip(), float(m.group(2)))
    return None


def default_source_behind_alias(run=None):
    """Best-effort ``(name, volume)`` of the device the OS default alias points at.

    ``default`` names a route, not a microphone (see :func:`is_routing_alias`), so on
    a PipeWire desktop this is the only way to say *which* microphone is being used.
    Shells out to ``wpctl``, the way this project already reaches ``notify-send`` and
    ``wl-copy``: used when present, absent without complaint, never required and
    never raising into a caller.
    """
    import subprocess

    def _default_run():
        return subprocess.run(
            ["wpctl", "status"], capture_output=True, text=True, timeout=3
        ).stdout

    try:
        return parse_wpctl_default_source((run or _default_run)())
    except Exception:  # pragma: no cover - depends on the host having wpctl
        return None
