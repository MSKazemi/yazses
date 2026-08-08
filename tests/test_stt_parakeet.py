"""ParakeetEngine (stt/parakeet.py) against a fake onnx_asr module.

The real onnx-asr package is never required in CI: a stub module is injected
into sys.modules, mirroring the API the engine codes against
(``load_model(name, quantization=...)`` → adapter with
``recognize(waveform, sample_rate=...)`` → str).
"""
from __future__ import annotations

import logging
import sys
import types

import numpy as np
import pytest

from yazses.config import SttConfig


class _FakeAdapter:
    def __init__(self, text: str = " hello world ") -> None:
        self.text = text
        self.calls: list[dict] = []

    def recognize(self, waveform, sample_rate=16000):
        self.calls.append({"waveform": waveform, "sample_rate": sample_rate})
        return self.text


def _install_fake_onnx_asr(monkeypatch, adapter: _FakeAdapter, *, int8_fails=False):
    loads: list[tuple[str, dict]] = []
    fake = types.ModuleType("onnx_asr")

    def load_model(name, **kwargs):
        loads.append((name, kwargs))
        if int8_fails and kwargs.get("quantization"):
            raise ValueError("no int8 files for this model")
        return adapter

    fake.load_model = load_model
    monkeypatch.setitem(sys.modules, "onnx_asr", fake)
    return loads


def _engine(monkeypatch, adapter=None, config=None, **fake_kw):
    from yazses.stt.parakeet import ParakeetEngine

    adapter = adapter or _FakeAdapter()
    loads = _install_fake_onnx_asr(monkeypatch, adapter, **fake_kw)
    eng = ParakeetEngine(config or SttConfig(engine="parakeet"))
    return eng, adapter, loads


def test_transcribe_returns_text(monkeypatch):
    eng, adapter, loads = _engine(monkeypatch)
    text = eng.transcribe(np.zeros(16000, dtype=np.float32), 16000)
    assert text == "hello world"
    # 16 kHz native rate: audio passes through unresampled.
    assert adapter.calls[0]["waveform"].size == 16000


def test_default_model_and_int8_quantization(monkeypatch):
    from yazses.stt.parakeet import DEFAULT_MODEL

    _eng, _adapter, loads = _engine(monkeypatch)
    # SttConfig.model defaults to a Whisper name (base.en) — never handed to onnx-asr.
    assert loads == [(DEFAULT_MODEL, {"quantization": "int8"})]


def test_parakeet_model_name_in_config_is_honoured(monkeypatch):
    cfg = SttConfig(engine="parakeet", model="nemo-parakeet-tdt-0.6b-v3")
    _eng, _adapter, loads = _engine(monkeypatch, config=cfg)
    assert loads[0][0] == "nemo-parakeet-tdt-0.6b-v3"


def test_quantization_failure_falls_back_to_default_precision(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="yazses.stt.parakeet"):
        _eng, _adapter, loads = _engine(monkeypatch, int8_fails=True)
    # First attempt with int8, then a plain load — the engine still comes up.
    assert loads[0][1] == {"quantization": "int8"}
    assert loads[1][1] == {}


def test_empty_audio_short_circuits(monkeypatch):
    eng, adapter, _loads = _engine(monkeypatch)
    assert eng.transcribe(np.array([], dtype=np.float32)) == ""
    assert adapter.calls == []


def test_translate_task_is_ignored_with_a_single_log(monkeypatch, caplog):
    eng, _adapter, _loads = _engine(monkeypatch)
    audio = np.zeros(16000, dtype=np.float32)
    with caplog.at_level(logging.WARNING, logger="yazses.stt.parakeet"):
        assert eng.transcribe(audio, 16000, task="translate") == "hello world"
        assert eng.transcribe(audio, 16000, task="translate") == "hello world"
    warnings = [r for r in caplog.records if "translate" in r.message]
    assert len(warnings) == 1  # warned once, not per burst


def test_non_english_language_warns_that_parakeet_cannot_honour_it(monkeypatch, caplog):
    """Parakeet TDT v2 is English-only; `[stt] language = "de"` must not look applied."""
    cfg = SttConfig(model="nemo-parakeet-tdt-0.6b-v2", language="de")
    with caplog.at_level(logging.WARNING, logger="yazses.stt.parakeet"):
        _engine(monkeypatch, config=cfg)
    assert "English-only" in caplog.text
    assert "faster-whisper" in caplog.text


def test_english_language_does_not_warn(monkeypatch, caplog):
    cfg = SttConfig(model="nemo-parakeet-tdt-0.6b-v2", language="en")
    with caplog.at_level(logging.WARNING, logger="yazses.stt.parakeet"):
        _engine(monkeypatch, config=cfg)
    assert "English-only" not in caplog.text


def test_initial_prompt_is_accepted_and_ignored(monkeypatch):
    eng, adapter, _loads = _engine(monkeypatch)
    audio = np.zeros(16000, dtype=np.float32)
    assert eng.transcribe(audio, 16000, initial_prompt="YazSes jargon") == "hello world"
    assert adapter.calls  # decode happened; no prompt kwarg exists to forward


def test_non_16k_audio_is_resampled(monkeypatch):
    eng, adapter, _loads = _engine(monkeypatch)
    eng.transcribe(np.zeros(8000, dtype=np.float32), sample_rate=8000)  # 1 s @ 8 kHz
    sent = adapter.calls[0]["waveform"]
    assert sent.size == 16000  # linearly upsampled to 1 s @ 16 kHz
    assert sent.dtype == np.float32


def test_transcribe_words_returns_text_and_empty_words(monkeypatch):
    """(text, []) is the documented 'no word timestamps' degradation — daemon
    callers guard with `if prosody_words` and skip prosody/confidence."""
    eng, _adapter, _loads = _engine(monkeypatch)
    text, words = eng.transcribe_words(np.zeros(16000, dtype=np.float32), 16000)
    assert text == "hello world"
    assert words == []


def test_decode_window_batch_decodes(monkeypatch):
    eng, _adapter, _loads = _engine(monkeypatch)
    assert eng.decode_window(np.zeros(16000, dtype=np.float32)) == "hello world"


def test_satisfies_the_stt_engine_protocol(monkeypatch):
    from yazses.stt.base import SttEngine

    eng, _adapter, _loads = _engine(monkeypatch)
    assert isinstance(eng, SttEngine)


def test_recognize_tolerates_adapters_without_sample_rate_kw(monkeypatch):
    class _OldAdapter:
        def __init__(self):
            self.calls = 0

        def recognize(self, waveform):  # no sample_rate kw (older onnx-asr)
            self.calls += 1
            return "ok"

    adapter = _OldAdapter()
    _install_fake_onnx_asr(monkeypatch, adapter)
    from yazses.stt.parakeet import ParakeetEngine

    eng = ParakeetEngine(SttConfig(engine="parakeet"))
    assert eng.transcribe(np.zeros(1600, dtype=np.float32)) == "ok"
    assert adapter.calls == 1


@pytest.mark.parametrize(
    "result,expected",
    [
        (None, ""),
        ("  text  ", "text"),
        (["a", " b "], "a b"),
        (types.SimpleNamespace(text=" rich "), "rich"),
    ],
)
def test_extract_text_is_liberal_about_result_shapes(result, expected):
    from yazses.stt.parakeet import ParakeetEngine

    assert ParakeetEngine._extract_text(result) == expected
