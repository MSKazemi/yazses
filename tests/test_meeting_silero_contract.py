"""The contract `meeting/silero_vad.py` relies on from `silero-vad` — pinned, mocked.

The backend is optional and heavy (torch), so CI never loads the real model. That is how
it shipped calling the model with a numpy slice: `OnnxWrapper.__call__` (5.1.2 through
6.2.3) begins with ``x.dim()``, which an ndarray does not have, so the first voiced chunk
raised ``AttributeError``. The fakes below encode what upstream's wrapper actually
requires and returns, so a change on either side fails here instead of in a meeting:

* ``load_silero_vad(onnx=True)`` — the bundled ONNX, no hub download;
* the model is called with a 1-D torch tensor of exactly 512 samples and ``sr=16000``;
* it returns a ``(1, 1)`` speech-probability tensor that ``float()`` accepts.

The last test checks the same contract against the real package where the extra is
installed, and skips everywhere else.
"""
from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from yazses.config import MeetingConfig
from yazses.meeting.silero_vad import make_silero_is_silent


class _FakeTensor:
    """The slice of the torch.Tensor API that silero-vad's `OnnxWrapper` touches."""

    def __init__(self, arr: np.ndarray) -> None:
        self._arr = arr
        self.shape = arr.shape

    def dim(self) -> int:
        return self._arr.ndim

    def __float__(self) -> float:
        if self._arr.size != 1:
            raise TypeError("only one-element tensors can be converted to Python scalars")
        return float(self._arr.reshape(-1)[0])


class _FakeOnnxWrapper:
    """Mirrors `silero_vad.utils_vad.OnnxWrapper.__call__`'s checks and output shape."""

    def __init__(self, prob_for) -> None:
        self.calls: list[tuple[tuple[int, ...], int]] = []
        self._prob_for = prob_for

    def __call__(self, x, sr: int):
        x.dim()  # upstream's first statement; an ndarray raises AttributeError here
        if sr != 16000:
            raise ValueError(f"unexpected sample rate {sr}")
        if x.shape[-1] != 512:
            raise ValueError(f"Provided number of samples is {x.shape[-1]}")
        self.calls.append((tuple(x.shape), sr))
        return _FakeTensor(np.array([[self._prob_for(x._arr)]], dtype="float32"))


@pytest.fixture
def fake_silero(monkeypatch):
    loads: list[dict] = []
    model = _FakeOnnxWrapper(lambda arr: 0.9 if np.abs(arr).max() > 0.1 else 0.05)

    def load_silero_vad(**kwargs):
        loads.append(kwargs)
        return model

    fake_torch = types.ModuleType("torch")
    fake_torch.from_numpy = lambda arr: _FakeTensor(arr)  # type: ignore[attr-defined]
    fake_sv = types.ModuleType("silero_vad")
    fake_sv.load_silero_vad = load_silero_vad  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "silero_vad", fake_sv)
    return model, loads


def test_loads_the_bundled_onnx_model(fake_silero):
    _, loads = fake_silero
    assert make_silero_is_silent(MeetingConfig(vad_backend="silero")) is not None
    assert loads == [{"onnx": True}]


def test_model_is_fed_512_sample_tensors_at_16k(fake_silero):
    model, _ = fake_silero
    is_silent = make_silero_is_silent(MeetingConfig(vad_backend="silero"))
    assert is_silent is not None
    assert is_silent(np.zeros(1600, dtype="float32")) is True
    # 1600 samples -> three whole 512-sample windows; the 64-sample tail is not sent.
    assert model.calls == [((512,), 16000)] * 3


def test_speech_window_makes_the_chunk_voiced(fake_silero):
    is_silent = make_silero_is_silent(MeetingConfig(vad_backend="silero"))
    assert is_silent is not None
    chunk = np.zeros(1600, dtype="float32")
    chunk[600:900] = 0.5
    assert is_silent(chunk) is False


def test_threshold_is_yazses_own(fake_silero):
    # The default (0.5) is kept explicit on YazSes's side, not inherited from upstream.
    assert MeetingConfig().silero_threshold == 0.5
    is_silent = make_silero_is_silent(MeetingConfig(vad_backend="silero", silero_threshold=0.95))
    assert is_silent is not None
    loud = np.full(1024, 0.5, dtype="float32")  # fake prob 0.9 < 0.95
    assert is_silent(loud) is True


def test_chunk_shorter_than_one_window_is_silent_without_a_call(fake_silero):
    model, _ = fake_silero
    is_silent = make_silero_is_silent(MeetingConfig(vad_backend="silero"))
    assert is_silent is not None
    assert is_silent(np.ones(100, dtype="float32")) is True
    assert model.calls == []


def test_missing_extra_returns_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "silero_vad", None)
    assert make_silero_is_silent(MeetingConfig(vad_backend="silero")) is None


def test_real_package_honours_the_same_contract():
    """Where the `silero` extra is installed, the real wrapper must match the fakes."""
    pytest.importorskip("onnxruntime", reason="the `silero` extra is optional")
    torch = pytest.importorskip("torch", reason="the `silero` extra is optional")
    silero_vad = pytest.importorskip("silero_vad", reason="the `silero` extra is optional")

    model = silero_vad.load_silero_vad(onnx=True)
    out = model(torch.from_numpy(np.zeros(512, dtype="float32")), 16000)
    assert tuple(out.shape) == (1, 1)
    assert 0.0 <= float(out) <= 1.0

    is_silent = make_silero_is_silent(MeetingConfig(vad_backend="silero"))
    assert is_silent is not None
    assert is_silent(np.zeros(1600, dtype="float32")) is True
