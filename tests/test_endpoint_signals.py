"""Signal building blocks for Ghost Ahead endpoint anticipation (spec-ghost-ahead).

These are the reusable, deterministic pieces the anticipator consumes: a
read-only "how long has the confirmed prefix held steady?" accessor on the
streaming engine, a trailing-energy-falling detector over the recorded buffer,
and a debounce so pre-warm cannot thrash on micro-pauses. All pure/unit-level;
no model, no audio device. Spec: design/specs/ghost-ahead.md.
"""
from __future__ import annotations

import numpy as np
import pytest

from yazses.audio.vad_calibrated import trailing_energy_falling
from yazses.config import AccessibilityConfig
from yazses.stt.endpoint import EndpointAnticipator
from yazses.stt.streaming import StreamingEngine

# ---- prefix_stable_for_ms() accessor ---------------------------------------

class _NoopModel:
    def transcribe(self, audio, **kwargs):  # pragma: no cover - never called here
        return [], None


def test_prefix_stable_for_ms_uses_injected_clock():
    clock = {"t": 100.0}
    eng = StreamingEngine(_NoopModel(), time_fn=lambda: clock["t"])
    eng.start()
    # No confirmed prefix change since start; 0.5 s elapse -> 500 ms stable.
    clock["t"] = 100.5
    assert eng.prefix_stable_for_ms() == pytest.approx(500.0)
    eng.stop()


def test_prefix_stable_resets_when_prefix_grows():
    clock = {"t": 0.0}
    eng = StreamingEngine(_NoopModel(), time_fn=lambda: clock["t"])
    eng.start()
    clock["t"] = 1.0
    eng._note_prefix_change()  # simulate the decode loop confirming new text
    clock["t"] = 1.2
    assert eng.prefix_stable_for_ms() == pytest.approx(200.0)
    eng.stop()


# ---- trailing_energy_falling() ---------------------------------------------

def test_trailing_energy_falling_true_when_amplitude_decays():
    cfg = AccessibilityConfig()
    # First half loud, second half quiet -> falling.
    audio = np.concatenate([
        np.full(8000, 0.5, dtype="float32"),
        np.full(8000, 0.05, dtype="float32"),
    ])
    assert trailing_energy_falling(audio, cfg, window_ms=1000, sample_rate=16000) is True


def test_trailing_energy_falling_false_when_steady_or_rising():
    cfg = AccessibilityConfig()
    steady = np.full(16000, 0.3, dtype="float32")
    assert trailing_energy_falling(steady, cfg, window_ms=1000, sample_rate=16000) is False
    rising = np.concatenate([
        np.full(8000, 0.05, dtype="float32"),
        np.full(8000, 0.5, dtype="float32"),
    ])
    assert trailing_energy_falling(rising, cfg, window_ms=1000, sample_rate=16000) is False


def test_trailing_energy_falling_false_on_empty():
    cfg = AccessibilityConfig()
    assert trailing_energy_falling(np.array([], dtype="float32"), cfg, window_ms=1000) is False


# ---- EndpointAnticipator debounce ------------------------------------------

def test_debounce_suppresses_second_fire_within_window():
    a = EndpointAnticipator(min_silence_s=0.3, stable_updates=1, debounce_s=0.5)
    assert a.observe("done", 0.4, now=10.0) is True       # first fire
    assert a.observe("done", 0.4, now=10.2) is False      # within 0.5 s -> suppressed
    assert a.observe("done", 0.4, now=10.6) is True       # debounce elapsed -> fires


def test_no_debounce_when_now_omitted_preserves_legacy_behaviour():
    a = EndpointAnticipator(min_silence_s=0.3, stable_updates=1, debounce_s=0.5)
    assert a.observe("done", 0.4) is True
    assert a.observe("done", 0.4) is True  # no clock -> debounce inert
