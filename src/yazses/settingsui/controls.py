"""The three settings people actually tweak, as Qt-free models (#62).

Feature toggles are booleans; these three are not, and each has a way of being
wrong that a checkbox cannot be:

* **Hotkey** — a key the platform cannot bind leaves the user with no way to
  dictate and no clue why, so the picker validates against the platform's own key
  map before writing anything.
* **Microphone** — the list has to mean the same thing as `yazses audio devices`
  (● default, ★ pinned) or the window and the CLI disagree about the machine.
* **VAD threshold** — the number that silently discards speech. A slider without
  a live level meter is a user guessing at a float; with one, they can *see* their
  voice sitting under the line.

Hardware access is injected, so all of this tests without a keyboard, a
microphone or Qt — the pattern the rest of `settingsui/` uses. Writes go through
`system/configedit.py::set_config_key`, which preserves comments and infers
types, so a threshold stays a number rather than becoming the string "0.004".
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from yazses.configcheck import enum_values

# A VAD threshold outside this range is not a setting, it is a broken microphone
# gate: 0 accepts silence as speech, and anything above ~0.2 rejects a shout.
VAD_MIN = 0.0001
VAD_MAX = 0.2
# Slider widgets are integral; this is the resolution the float is quantised to.
VAD_SLIDER_STEPS = 1000


#: How a finished transcript reaches the focused window. Mirrors `[injection]
#: backend` — an unrecognised value falls through to `auto` at runtime, so the
#: window refuses one rather than showing a setting that reads back as the user's
#: while doing something else.
#: Taken from `configcheck`, not restated here. The loader now rejects a value outside
#: this set, and two copies of a closed set disagree the first time one is extended --
#: at which point the window would offer a value the loader throws away, or refuse one it
#: accepts.
INJECTION_BACKENDS: tuple[str, ...] = enum_values("injection", "backend") or ()

#: `[injection] target_guard` — what happens when you dictate with no editable
#: field focused. Label → value, because "clipboard" does not say what it does.
#: Labels are the window's own; the *values* come from the same table the loader
#: validates against, and a test pins them equal.
TARGET_GUARDS: tuple[tuple[str, str], ...] = (
    ("Copy it to the clipboard and tell me", "clipboard"),
    ("Type it anyway, but warn me", "warn"),
    ("No guard — always type", "off"),
)

#: Fallback compute types when ctranslate2 cannot be asked (see
#: `compute_type_choices`). Deliberately the conservative CPU set: these four are
#: what a CPU build reports, and offering float16 on a machine that cannot do it
#: is how you get a settings window that writes a config the daemon rejects.
_FALLBACK_COMPUTE_TYPES: tuple[str, ...] = ("int8", "int8_float32", "int16", "float32")

#: The pre-speech padding range, in ms. Below the floor the first word is clipped,
#: which is the fault this setting exists to fix; above the ceiling every burst
#: carries most of a second of silence into the decoder for nothing.
PADDING_MIN_MS = 0
PADDING_MAX_MS = 2000


def compute_type_choices(device: str = "cpu", current: str = "") -> list[str]:
    """The quantisations *this machine* can actually run, plus what is configured.

    Asked of ctranslate2 rather than hardcoded, because the answer is a property of
    the CPU: an AVX-512 machine reports a different set from an older one, and a CUDA
    build reports a different set again. A fixed list would offer values that load
    fine on the developer's box and fail on the user's.

    The failure it prevents is worth naming. An unsupported compute type raises out of
    `WhisperModel(...)`, which `stt/faster_whisper.py` catches and re-raises as
    `ModelUnavailableError` — a message about the *model* being unavailable, listing
    three ways to obtain a model the user already has. The cause is a quantisation
    string, and nothing anywhere says so.

    Never raises: ctranslate2 is a compiled extension, and `get_supported_compute_types`
    probes the device, which is exactly the call that fails on a broken CUDA install.
    The settings window has to open there — every other setting still works.
    """
    try:
        # ctranslate2 ships no py.typed marker, so mypy cannot see into it. The
        # call below is guarded by the surrounding try/except anyway.
        import ctranslate2  # type: ignore[import-untyped]

        supported = set(ctranslate2.get_supported_compute_types(device or "cpu"))
    except Exception:
        supported = set(_FALLBACK_COMPUTE_TYPES)
    names = sorted(n for n in supported if n)
    chosen = (current or "").strip()
    # Same rule as `model_choices`: a hand-configured value is never silently
    # replaced by the first entry in a list, even when this build cannot offer it.
    if chosen and chosen not in names:
        return [chosen, *names]
    return names


def target_guard_choices(current: str = "") -> list[tuple[str, str]]:
    """The no-text-target dropdown, keeping a configured value that is not listed."""
    rows = list(TARGET_GUARDS)
    chosen = (current or "").strip()
    if chosen and all(chosen != value for _, value in rows):
        rows.insert(0, (f"{chosen} (from your config)", chosen))
    return rows


def clamp_padding_ms(value) -> int:
    """Keep the pre-speech padding inside the range where it means something.

    Clamped rather than refused, like the VAD threshold: a spin box cannot produce
    an out-of-range value, so a refusal here would only ever be API misuse, and
    silently dropping the edit is worse than pinning it to the edge.
    """
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return PADDING_MIN_MS
    return min(PADDING_MAX_MS, max(PADDING_MIN_MS, number))

#: Label → `[stt] language` value. Whisper accepts far more than this; the list is
#: the common ones plus whatever the config already holds, because a dropdown of
#: ninety-nine codes is a worse way to find "de" than typing it.
#:
#: "" is a real value, not a blank: it auto-detects per utterance.
LANGUAGE_CHOICES: tuple[tuple[str, str], ...] = (
    ("Auto-detect (per utterance)", ""),
    ("English", "en"),
    ("Persian / فارسی", "fa"),
    ("German", "de"),
    ("French", "fr"),
    ("Spanish", "es"),
    ("Italian", "it"),
    ("Dutch", "nl"),
    ("Portuguese", "pt"),
    ("Russian", "ru"),
    ("Turkish", "tr"),
    ("Arabic", "ar"),
    ("Hindi", "hi"),
    ("Chinese", "zh"),
    ("Japanese", "ja"),
    ("Korean", "ko"),
)


def model_choices(known: Iterable[str], current: str = "") -> list[str]:
    """The model dropdown: the known checkpoints, plus whatever is configured.

    *known* is an iterable of names, which a ``{name: repo}`` registry satisfies by
    iterating its keys — that is exactly how `WHISPER_MODELS` is passed, and typing
    it as a sequence claimed an ordering this never relies on.

    A hub id (``org/repo``) or a filesystem path is a legitimate model that will
    never appear in the known set, so a hand-edited config must not have its
    choice silently replaced by the first entry in a list — the same rule the
    hotkey picker follows.

    Sorted so the ``.en`` and multilingual pairs sit together rather than in the
    mapping's insertion order.
    """
    names = sorted({n for n in known if n})
    chosen = (current or "").strip()
    if chosen and chosen not in names:
        return [chosen, *names]
    return names


def language_choices(current: str = "") -> list[tuple[str, str]]:
    """The language dropdown, keeping a configured code that is not in the list."""
    rows = list(LANGUAGE_CHOICES)
    chosen = (current or "").strip()
    if chosen and all(chosen != value for _, value in rows):
        rows.insert(1, (f"{chosen} (from your config)", chosen))
    return rows


@dataclass(frozen=True)
class MicChoice:
    """One row of the microphone dropdown."""

    label: str
    value: str          # what goes in `[audio] device`; "" follows the OS default
    is_default: bool = False
    is_pinned: bool = False


def supported_hotkeys(key_map: dict[str, int] | Sequence[str]) -> list[str]:
    """The key names this platform can actually bind, sorted for display."""
    names = key_map.keys() if isinstance(key_map, dict) else key_map
    return sorted(names)


def validate_hotkey(name: str, key_map) -> str | None:
    """None when *name* is bindable here, otherwise why not.

    Writing an unbindable key leaves the user with no way to dictate and no
    message explaining it — the picker refuses instead.
    """
    cleaned = (name or "").strip().lower()
    if not cleaned:
        return "no key was captured"
    supported = set(supported_hotkeys(key_map))
    if cleaned not in supported:
        return (
            f"{name!r} cannot be used as a hold-to-talk key on this platform. "
            f"Supported: {', '.join(sorted(supported))}"
        )
    return None


def mic_choices(
    devices: Sequence,
    *,
    default_name: str | None,
    pinned: str,
) -> list[MicChoice]:
    """Build the dropdown, mirroring `yazses audio devices` exactly.

    The first row is always "follow the system default" — which is what an empty
    `[audio] device` means, and the state most people should be in. Pinning is
    for when a device *steals* capture, not the normal case.
    """
    rows = [MicChoice(
        label="Follow the system default"
              + (f" (currently {default_name})" if default_name else ""),
        value="",
        is_default=True,
        is_pinned=not pinned,
    )]
    for device in devices:
        name = getattr(device, "name", str(device))
        marks = ""
        if default_name and name == default_name:
            marks += " ●"
        # `[audio] device` is matched as a substring by the recorder, so a pinned
        # value is a *substring* of the device name, not necessarily equal to it.
        if pinned and pinned.lower() in name.lower():
            marks += " ★"
        rows.append(MicChoice(
            label=f"{name}{marks}",
            value=name,
            is_default=bool(default_name and name == default_name),
            is_pinned=bool(pinned and pinned.lower() in name.lower()),
        ))
    return rows


def clamp_threshold(value: float) -> float:
    """Keep a threshold inside the range where it means something."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return VAD_MIN
    return min(VAD_MAX, max(VAD_MIN, number))


def threshold_to_slider(value: float) -> int:
    """Map a threshold to an integer slider position.

    Logarithmic, because the useful range spans three orders of magnitude
    (0.0005 for a quiet voice, 0.05 for a noisy room) and a linear slider would
    put every usable value in the leftmost pixel.
    """
    import math

    value = clamp_threshold(value)
    span = math.log10(VAD_MAX) - math.log10(VAD_MIN)
    position = (math.log10(value) - math.log10(VAD_MIN)) / span
    return int(round(position * VAD_SLIDER_STEPS))


def slider_to_threshold(position: int) -> float:
    """Inverse of :func:`threshold_to_slider`, rounded to a readable float."""
    import math

    steps = max(0, min(VAD_SLIDER_STEPS, int(position)))
    span = math.log10(VAD_MAX) - math.log10(VAD_MIN)
    value = 10 ** (math.log10(VAD_MIN) + span * (steps / VAD_SLIDER_STEPS))
    # 4 significant figures: enough resolution, and it does not write
    # 0.004000000000000001 into someone's config file.
    return float(f"{value:.4g}")


def meter_reading(level: float, threshold: float) -> tuple[int, bool]:
    """Level as a 0–100 bar, plus whether it currently clears the gate.

    The boolean is the whole point of the meter: it answers "is my voice above
    the line?", which is the question behind every "Silent audio -- discarding"
    report.
    """
    position = min(100, max(0, threshold_to_slider(max(level, VAD_MIN)) * 100 // VAD_SLIDER_STEPS))
    return int(position), bool(level >= threshold)


def recommend_threshold(speech_level: float, *, headroom: float = 0.5) -> float:
    """A threshold that sits below measured speech, with room to spare.

    Half of the measured level: high enough to reject a quiet room, low enough
    that a softer sentence still passes. Mirrors what `yazses mic-level --set`
    writes, so the window and the CLI cannot recommend different numbers.
    """
    return clamp_threshold(max(speech_level, VAD_MIN) * headroom)


def apply_setting(
    section: str,
    key: str,
    value,
    *,
    write: Callable[[str, str, object], bool],
) -> tuple[bool, str]:
    """Write one setting and produce the message the window should show."""
    try:
        ok = bool(write(section, key, value))
    except Exception as exc:  # noqa: BLE001 - surfaced, never raised at Qt
        return False, f"Could not save [{section}] {key}: {exc}"
    if not ok:
        return False, f"Could not save [{section}] {key}."
    return True, f"Saved [{section}] {key} = {value!r}. Restart YazSes to apply."
