"""Earcon motif grammar + waveform synth (pure) — ADR-v2-096.

Map a daemon event to a short non-speech tone motif and render it to a numpy waveform. Pure and
deterministic; numpy is already a core dependency.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ToneSpec:
    """One tone: frequency, duration, and envelope shape (``linear`` | ``buzz``)."""
    freq_hz: float
    dur_ms: int
    envelope: str = "linear"


_EARCONS = {
    "recording_start": [ToneSpec(660, 90), ToneSpec(990, 110)],   # rising two-note
    "recording_stop": [ToneSpec(990, 90), ToneSpec(660, 110)],    # falling two-note
    "command_done": [ToneSpec(880, 70), ToneSpec(1320, 70)],      # bright chime
    "low_confidence": [ToneSpec(220, 150, "buzz")],               # muted buzz
    "error": [ToneSpec(160, 200, "buzz")],
    "idle": [ToneSpec(440, 60)],
}
_LOW_CONFIDENCE = 0.5


def earcon_for(event: str, confidence=None):
    """Return the tone motif for ``event`` (low ``confidence`` overrides to a buzz). Pure."""
    if confidence is not None and confidence < _LOW_CONFIDENCE:
        return list(_EARCONS["low_confidence"])
    return list(_EARCONS.get(event, _EARCONS["idle"]))


def _envelope(kind: str, n: int) -> np.ndarray:
    if n <= 0:
        return np.zeros(0)
    if kind == "buzz":
        t = np.arange(n)
        return 0.6 * (0.5 * (1.0 + np.sign(np.sin(2.0 * np.pi * 8.0 * t / n))))
    ramp = max(1, n // 10)
    env = np.ones(n)
    env[:ramp] = np.linspace(0.0, 1.0, ramp)
    env[-ramp:] = np.linspace(1.0, 0.0, ramp)
    return env


def render_earcon(specs, fs: int = 44100) -> np.ndarray:
    """Render a list of :class:`ToneSpec` to a mono float waveform. Pure."""
    chunks = []
    for s in specs or ():
        n = int(fs * s.dur_ms / 1000)
        if n <= 0:
            continue
        t = np.arange(n) / fs
        wave = np.sin(2.0 * np.pi * s.freq_hz * t) * _envelope(s.envelope, n)
        chunks.append(wave)
    return np.concatenate(chunks) if chunks else np.zeros(0)
