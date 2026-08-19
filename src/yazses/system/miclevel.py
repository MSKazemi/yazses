"""Microphone level measurement and VAD-threshold calibration.

Backs the ``yazses mic-level`` command. The daemon's VAD discards a clip when
``mean(|audio|) < accessibility.vad_threshold`` (see audio/vad_calibrated.py),
so the relevant measurement is the whole-clip mean absolute amplitude while the
user is speaking. We recommend a threshold safely below that level but above a
floor, so silence is still rejected.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Never recommend a threshold below this — protects against picking up room
# noise / DC offset as if it were speech.
_MIN_THRESHOLD = 0.002
# Fraction of the measured speech level to place the threshold at, leaving
# headroom so quieter words in the same register still pass the gate.
_HEADROOM = 0.5


@dataclass
class LevelStats:
    """Result of analysing a recorded sample."""

    duration_s: float
    mean_abs: float          # the metric the VAD actually compares
    peak: float
    recommended_threshold: float
    is_silent: bool          # true if essentially no signal was captured


def analyze(audio: np.ndarray, sample_rate: int) -> LevelStats:
    """Compute level statistics and a recommended VAD threshold for a sample."""
    if audio.size == 0:
        return LevelStats(0.0, 0.0, 0.0, _MIN_THRESHOLD, is_silent=True)
    mean_abs = float(np.abs(audio).mean())
    peak = float(np.abs(audio).max())
    recommended = max(_MIN_THRESHOLD, round(mean_abs * _HEADROOM, 4))
    # Below the floor there is no usable signal to calibrate against.
    is_silent = mean_abs < _MIN_THRESHOLD
    return LevelStats(
        duration_s=audio.size / sample_rate,
        mean_abs=mean_abs,
        peak=peak,
        recommended_threshold=recommended,
        is_silent=is_silent,
    )


def record(
    seconds: float, sample_rate: int = 16000, device: str | int | None = None
) -> np.ndarray:
    """Record ``seconds`` of mono float32 audio.

    ``device`` pins the input: a name substring (resolved against the current device
    list), an explicit PortAudio index, or None to follow the OS default. Pinning lets
    ``yazses mic-level`` and the daemon's re-calibrate action measure the *active* mic
    rather than whatever the OS default happens to be.
    """
    import sounddevice as sd

    device_index: int | None = None
    if isinstance(device, int):
        device_index = device
    elif isinstance(device, str) and device.strip():
        from yazses.audio.devices import list_input_devices, resolve_input_device

        device_index = resolve_input_device(device, list_input_devices())

    frames = int(seconds * sample_rate)
    buf = sd.rec(
        frames, samplerate=sample_rate, channels=1, dtype="float32", device=device_index
    )
    sd.wait()
    return np.asarray(buf, dtype=np.float32).flatten()


def _section_span(text: str, section: str):
    """``(start, end)`` character offsets of *section*'s body, or ``(None, None)``. Pure.

    The body runs from just after the ``[section]`` header to the next header or the end
    of the file, so an edit inside it cannot reach a neighbouring section's keys.
    """
    header = re.search(rf"(?m)^\[{re.escape(section)}\]\s*$", text)
    if not header:
        return None, None
    nxt = re.search(r"(?m)^\[[^\]]+\]\s*$", text[header.end():])
    end = header.end() + nxt.start() if nxt else len(text)
    return header.end(), end


def update_threshold_in_config(path: Path, threshold: float) -> str:
    """Set ``[accessibility] vad_threshold`` in a TOML file, preserving comments.

    Returns a short human-readable description of what changed. Creates the file
    and/or the ``[accessibility]`` section if missing.
    """
    line = f"vad_threshold = {threshold}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"[accessibility]\n{line}\n")
        return f"created {path} with {line}"

    text = path.read_text()
    # Replace an existing assignment, but only one that is actually INSIDE
    # [accessibility]. This used to substitute `vad_threshold` anywhere in the file, so a
    # key a user had put under the wrong section was rewritten instead -- and the function
    # reported "updated" while the setting that matters kept its old value. `configcheck`
    # already prints "[audio] vad_threshold: is not a known setting; ignored" about that
    # very line, so the mistake was visible to the system and edited anyway.
    #
    # `yazses mic-level --set` is what the docs recommend when words are being dropped, so
    # the failure lands exactly where the user is already stuck: told it worked, dictation
    # still failing.
    start, end = _section_span(text, "accessibility")
    if start is not None:
        block = text[start:end]
        new_block, n = re.subn(r"(?m)^[ \t]*vad_threshold[ \t]*=.*$", line, block)
        if n:
            path.write_text(text[:start] + new_block + text[end:])
            return f"updated {line}"

    # No existing key: insert under [accessibility] if present, else append it.
    if re.search(r"(?m)^\[accessibility\]\s*$", text):
        new_text = re.sub(
            r"(?m)^(\[accessibility\]\s*)$", r"\1\n" + line, text, count=1
        )
    else:
        sep = "" if text.endswith("\n") or not text else "\n"
        new_text = f"{text}{sep}\n[accessibility]\n{line}\n"
    path.write_text(new_text)
    return f"added {line}"
