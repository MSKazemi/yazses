"""Tests for the accessibility enrollment wizard."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np


def make_mock_recorder(noise_level=0.002, speech_level=0.1):
    """Return a mock AudioRecorder that returns realistic audio."""
    sr = 16000
    noise = np.random.uniform(-noise_level, noise_level, sr * 3).astype(np.float32)
    speech_part = np.random.uniform(-speech_level, speech_level, sr * 2).astype(np.float32)
    audio = np.concatenate([noise, speech_part])

    recorder = MagicMock()
    recorder.start = MagicMock()
    recorder.stop = MagicMock(return_value=audio)
    return recorder


def test_run_wizard_returns_valid_thresholds(tmp_path, monkeypatch):
    """Wizard should derive vad_threshold and min_silence_ms within expected ranges."""
    # Load expected ranges
    stats_path = Path(__file__).parent / "fixtures" / "accessibility" / "rms_stats.json"
    with open(stats_path, encoding="utf-8") as f:
        stats = json.load(f)

    from yazses.accessibility.enroll import run_wizard

    # Mock input() to avoid blocking
    monkeypatch.setattr("builtins.input", lambda _: "")
    # Mock time.sleep to speed up test
    monkeypatch.setattr("time.sleep", lambda _: None)

    call_count = [0]
    def recorder_factory():
        call_count[0] += 1
        return make_mock_recorder(noise_level=0.002, speech_level=0.1)

    output_lines = []
    result = run_wizard(
        config_path=None,
        recorder_factory=recorder_factory,
        output_fn=lambda s: output_lines.append(s),
    )

    vt = result["vad_threshold"]
    ms = result["min_silence_ms"]
    lo, hi = stats["expected_vad_threshold_range"]
    assert lo <= vt <= hi, f"vad_threshold {vt} not in [{lo}, {hi}]"
    ms_lo, ms_hi = stats["expected_min_silence_ms_range"]
    assert ms_lo <= ms <= ms_hi, f"min_silence_ms {ms} not in [{ms_lo}, {ms_hi}]"


def test_run_wizard_writes_config(tmp_path, monkeypatch):
    """Wizard should write derived values to config.toml."""
    from yazses.accessibility.enroll import run_wizard

    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr("time.sleep", lambda _: None)

    config_path = tmp_path / "config.toml"

    def recorder_factory():
        return make_mock_recorder()

    run_wizard(
        config_path=config_path,
        recorder_factory=recorder_factory,
        output_fn=lambda s: None,
    )

    assert config_path.exists()
    import tomllib
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    assert "accessibility" in data
    assert "vad_threshold" in data["accessibility"]
