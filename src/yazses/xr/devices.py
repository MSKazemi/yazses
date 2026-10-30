"""Device capability profiles for the XR voice-input adapter (pure, static).

What each class of headset, glasses or companion can provide, so the Modality Role
Router (ADR-v2-011) can be given a sensible preset. The registry is deliberately
timid: a capability is ``True``/``False`` only when the repo's own research
(``design/research/waves/03-ar-wearables.md``) or ADR-v2-013 says so, or when it is
safe by construction. Everything else is ``None`` = UNKNOWN — never ``False`` — and
unknown never upgrades a preset. Real capabilities must be queried from the runtime.
"""
from __future__ import annotations

from dataclasses import dataclass

from yazses.xr import routes

# Names of the modality presets in modality/router.py PRESETS. Hard-coded so this module
# stays dependency-free; tests/test_xr_devices.py checks them against the real table.
PRESET_BALANCED = "balanced"
PRESET_HANDS_FREE = "hands-free"
PRESET_VOICE_ONLY = "voice-only"

_RESEARCH = "design/research/waves/03-ar-wearables.md"
_ADR_013 = "design/adr/adr-v2-013-glasses-desktop-bridge.md"


@dataclass(frozen=True)
class Source:
    """One literal quotation that supports one known (True/False) capability value.

    ``quote`` must occur verbatim (whitespace-collapsed) in ``path``, a repo file;
    ``tests/test_xr_devices.py`` greps it. ``capability`` is the DeviceProfile field.
    """

    capability: str
    path: str
    quote: str


@dataclass(frozen=True)
class DeviceProfile:
    """What one class of device can provide. ``None`` means unknown, not "no".

    A capability is only ever ``True``/``False`` with a matching :class:`Source`."""

    key: str
    display_name: str
    has_eye_tracking: bool | None
    has_hand_tracking: bool | None
    has_microphone_stream: bool | None
    companion: str
    notes: str
    evidence: str
    # Every True/False capability above needs a Source here; None needs none.
    sources: tuple[Source, ...] = ()


_PROFILES: tuple[DeviceProfile, ...] = (
    DeviceProfile(
        key="phone-companion",
        display_name="Phone companion (mic + pointing)",
        has_eye_tracking=None,
        has_hand_tracking=None,
        has_microphone_stream=True,
        companion="phone app on the paired bridge",
        notes="Near-term path: the phone is the microphone and the pointer.",
        evidence=(
            "ADR-v2-013 (glasses-desktop bridge) says 'phone-as-mic works now' and is "
            "the only thing it says about this device; it never mentions eye or gaze "
            "tracking, so eye tracking is unknown, not 'no'"
        ),
        sources=(Source("has_microphone_stream", _ADR_013, "phone-as-mic works now"),),
    ),
    DeviceProfile(
        key="generic-openxr",
        display_name="Generic OpenXR runtime",
        has_eye_tracking=None,
        has_hand_tracking=None,
        has_microphone_stream=None,
        companion="on-device companion app",
        notes="Extensions are optional in OpenXR; ask the runtime what it grants.",
        evidence="capability must be queried at runtime via the runtime, not assumed",
    ),
    DeviceProfile(
        key="meta-quest",
        display_name="Meta Quest",
        has_eye_tracking=None,
        has_hand_tracking=None,
        has_microphone_stream=None,
        companion="on-device companion app",
        notes="Varies by model; query the runtime.",
        evidence=(
            f"{_RESEARCH} does not describe Quest hardware; "
            "no capability is asserted, query at runtime"
        ),
    ),
    DeviceProfile(
        key="ray-ban-meta",
        display_name="Ray-Ban Meta glasses",
        has_eye_tracking=None,
        has_hand_tracking=None,
        has_microphone_stream=None,
        companion="phone app (phone-as-mic is the near-term path)",
        notes="Closed hardware; the research names Ray-Ban Display and the Neural Band.",
        evidence=(
            f"{_RESEARCH}: 'glasses hardware is closed -> phone-as-mic near-term'; "
            "no mic stream or tracking is stated for this device"
        ),
    ),
    DeviceProfile(
        key="android-xr",
        display_name="Android XR (Samsung Galaxy XR)",
        has_eye_tracking=None,
        has_hand_tracking=True,
        has_microphone_stream=None,
        companion="on-device companion app",
        notes="Voice-first OS model; the research calls it cloud-tethered and vendor-locked.",
        evidence=(
            f"{_RESEARCH}: Android XR 'fuses gaze+hand+voice+visual' - an OS-level "
            "statement. It does not say an app receives a raw gaze ray, so eye tracking "
            "is unknown; a desktop-readable mic stream is not stated either"
        ),
        sources=(Source("has_hand_tracking", _RESEARCH, "fuses gaze+hand+voice+visual"),),
    ),
    DeviceProfile(
        key="vision-pro",
        display_name="Apple Vision Pro",
        has_eye_tracking=None,
        has_hand_tracking=True,
        has_microphone_stream=None,
        companion="on-device companion app",
        notes=(
            "Gaze-target + pinch is the shipped spatial default; text entry is slow. "
            "Eye tracking is unknown here because the headset tracks eyes but the platform "
            "does not hand an app a gaze ray (docs/xr-visionos.md); hand tracking needs a "
            "Full Space and the user's permission."
        ),
        evidence=(
            f"{_RESEARCH}: 'Vision Pro gaze-target + pinch' is the shipped spatial "
            "default - an OS-level interaction statement. It does not say an app "
            "receives a raw gaze ray, so eye tracking is unknown; a desktop-readable "
            "mic stream is not stated"
        ),
        sources=(Source("has_hand_tracking", _RESEARCH, "Vision Pro gaze-target + pinch"),),
    ),
)

_BY_KEY: dict[str, DeviceProfile] = {p.key: p for p in _PROFILES}


def keys() -> tuple[str, ...]:
    """Profile keys in registry order."""
    return tuple(p.key for p in _PROFILES)


def get(key: str) -> DeviceProfile:
    """Look a profile up by key; the KeyError lists the valid keys."""
    try:
        return _BY_KEY[key]
    except (KeyError, TypeError):
        raise KeyError(f"unknown XR device {key!r}; known devices: {', '.join(keys())}") from None


def companion_routes(key: str) -> tuple[routes.Route, ...]:
    """Companion-app routes (OpenXR, WebXR, visionOS) that can reach this device."""
    return routes.routes_for_device(get(key).key)


def suggest_preset(profile: DeviceProfile) -> str:
    """A modality preset name using ONLY capabilities known to be True.

    Unknown (``None``) and ``False`` are treated alike: they never upgrade the preset.
    Known eye tracking gives gaze targeting (``hands-free``); known hand tracking alone
    gives pinch-to-activate (``balanced``); otherwise voice carries dictation alone.
    """
    if profile.has_eye_tracking is True:
        return PRESET_HANDS_FREE
    if profile.has_hand_tracking is True:
        return PRESET_BALANCED
    return PRESET_VOICE_ONLY


def _tri(value: bool | None) -> str:
    """Render a tri-state: unknown is never shown as 'no'."""
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def render_table() -> str:
    """A plain-text, deterministic table of every profile (registry order)."""
    header = ("device", "eye", "hand", "mic", "preset")
    rows = [
        (p.key, _tri(p.has_eye_tracking), _tri(p.has_hand_tracking),
         _tri(p.has_microphone_stream), suggest_preset(p))
        for p in _PROFILES
    ]
    widths = [max(len(r[i]) for r in (header, *rows)) for i in range(len(header))]

    def line(cells: tuple[str, ...]) -> str:
        return "  ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True)).rstrip()

    out = [line(header), line(tuple("-" * w for w in widths))]
    out += [line(r) for r in rows]
    out.append("")
    out.append("unknown = not stated by the repo's research; query the runtime, do not assume.")
    return "\n".join(out)
