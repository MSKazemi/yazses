"""The non-speech models that fetch on their own go through ``ensure_model`` (#932).

No network and no optional extra: the downloader and the third-party loaders are fakes.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

from yazses import cli
from yazses.gaze import download as gaze_download
from yazses.models import registry as reg
from yazses.system.hfcache import load_cache_first


@pytest.fixture(autouse=True)
def _online(monkeypatch):
    """Neither offline variable set, whatever the shell or an earlier import says."""
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    constants = sys.modules.get("huggingface_hub.constants")
    if constants is not None:
        monkeypatch.setattr(constants, "HF_HUB_OFFLINE", False, raising=False)


@pytest.fixture
def decisions(monkeypatch):
    """Every ``ensure_model`` call as (kind, name, policy, status); the real function runs."""
    seen: list[tuple[str, str, str, str]] = []
    real = reg.ensure_model

    def spy(kind, name, policy="auto", **kw):
        result = real(kind, name, policy, **kw)
        seen.append((kind, name, policy, result.status))
        return result

    monkeypatch.setattr(reg, "ensure_model", spy)
    return seen


# --- the camera face model ----------------------------------------------------------------


def test_a_missing_face_model_is_fetched_through_ensure_model(tmp_path, monkeypatch, decisions):
    dest = tmp_path / "sub" / "face_landmarker.task"
    said: list[str] = []
    monkeypatch.setattr(gaze_download, "_fetch", lambda url, path: path.write_bytes(b"m"))
    assert gaze_download.ensure_face_landmarker(dest, echo=said.append) == dest
    assert decisions == [("gaze", "face-landmarker", "auto", "downloaded")]
    assert said == [f"Downloading gaze model (~3.7 MB) → {dest} ..."]


def test_a_cached_face_model_is_ready_and_silent(tmp_path, monkeypatch, decisions):
    dest = tmp_path / "face_landmarker.task"
    dest.write_bytes(b"m")
    monkeypatch.setattr(gaze_download, "_fetch", lambda *a: pytest.fail("must not download"))
    said: list[str] = []
    assert gaze_download.ensure_face_landmarker(dest, echo=said.append) == dest
    assert decisions == [("gaze", "face-landmarker", "auto", "ready")] and not said


def test_an_empty_face_model_file_is_fetched_again(tmp_path, monkeypatch):
    dest = tmp_path / "face_landmarker.task"
    dest.write_bytes(b"")
    calls: list[str] = []
    monkeypatch.setattr(gaze_download, "_fetch", lambda url, path: calls.append(url))
    gaze_download.ensure_face_landmarker(dest)
    assert calls == [gaze_download.FACE_LANDMARKER_URL]


def test_a_blocked_face_model_download_raises_its_own_error(tmp_path, monkeypatch):
    boom = OSError("blocked by firewall")

    def blocked(url, path):
        raise boom

    monkeypatch.setattr(gaze_download, "_fetch", blocked)
    with pytest.raises(OSError) as caught:
        gaze_download.ensure_face_landmarker(tmp_path / "face_landmarker.task")
    assert caught.value is boom


# --- models a library fetches by name ------------------------------------------------------


def _loader(*outcomes):
    """A loader that records ``HF_HUB_OFFLINE`` per call and returns or raises in turn."""
    seen: list[str | None] = []
    queue = list(outcomes)

    def load():
        seen.append(os.environ.get("HF_HUB_OFFLINE"))
        outcome = queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return load, seen


def _routed(load, policy="auto"):
    return load_cache_first(
        load, what="a model", kind="diarization", name="pyannote", policy=policy,
        manual_hint="https://example.invalid/m",
    )


@pytest.mark.parametrize("policy", reg.POLICIES)
def test_a_cached_model_loads_under_every_policy_without_the_network(policy, decisions):
    load, seen = _loader("model")
    assert _routed(load, policy) == "model"
    assert seen == ["1"]
    assert decisions == [("diarization", "pyannote", policy, "ready")]


def test_a_missing_model_is_downloaded_under_auto(decisions):
    load, seen = _loader(FileNotFoundError("not cached"), "downloaded")
    assert _routed(load) == "downloaded"
    assert seen == ["1", None]
    assert decisions == [("diarization", "pyannote", "auto", "downloaded")]


def test_a_failed_download_raises_the_same_error_without_the_cache_miss_chained():
    boom = ConnectionError("the network is down")
    load, _ = _loader(FileNotFoundError("not cached"), boom)
    with pytest.raises(ConnectionError) as caught:
        _routed(load)
    assert caught.value is boom
    assert caught.value.__context__ is None


def test_offline_mode_still_gets_one_attempt_and_its_own_error(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    boom = FileNotFoundError("not cached")
    load, seen = _loader(boom)
    with pytest.raises(FileNotFoundError) as caught:
        _routed(load)
    assert caught.value is boom and seen == ["1"]


def test_a_loader_that_returns_none_is_not_retried():
    """pyannote answers some gated repos with ``None``; the adapter words that itself."""
    load, seen = _loader(None)
    assert _routed(load) is None
    assert seen == ["1"]


@pytest.mark.parametrize("policy", ["ask", "never"])
def test_ask_and_never_do_not_download(policy):
    load, seen = _loader(FileNotFoundError("not cached"))
    with pytest.raises(RuntimeError) as caught:
        _routed(load, policy)
    assert seen == ["1"], "only the cache-only attempt may run"
    message = str(caught.value)
    assert "pyannote" in message and "https://example.invalid/m" in message
    assert "--download-models" not in message, "that command fetches the sherpa files"


def _module(monkeypatch, name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def test_the_speaker_encoder_is_routed(monkeypatch, decisions):
    class Classifier:
        @staticmethod
        def from_hparams(**kw):
            return "encoder"

    _module(monkeypatch, "torch")
    _module(monkeypatch, "speechbrain")
    _module(monkeypatch, "speechbrain.inference")
    _module(monkeypatch, "speechbrain.inference.speaker", EncoderClassifier=Classifier)
    from yazses.voiceprint.ecapa import EcapaEmbedder

    EcapaEmbedder(types.SimpleNamespace())
    assert decisions == [("diarization", "ecapa", "auto", "ready")]


def test_the_pyannote_pipeline_is_routed(monkeypatch, decisions):
    class Pipeline:
        @staticmethod
        def from_pretrained(*a, **kw):
            return Pipeline()

        def to(self, device):
            return self

    monkeypatch.setenv("PYANNOTE_METRICS_ENABLED", "false")
    _module(monkeypatch, "torch", device=lambda kind: kind)
    _module(monkeypatch, "pyannote")
    _module(monkeypatch, "pyannote.audio", Pipeline=Pipeline)
    from yazses.recimport.pyannote_backend import PyannoteDiarizer

    PyannoteDiarizer(types.SimpleNamespace(min_speakers=0, max_speakers=0))
    assert decisions == [("diarization", "pyannote", "auto", "ready")]


# --- sherpa diarization: explicit only ----------------------------------------------------


def test_a_diarized_run_without_the_sherpa_models_does_not_download_them(tmp_path, monkeypatch):
    from yazses.recimport.factory import build_diarizer

    _module(monkeypatch, "sherpa_onnx")
    monkeypatch.setattr(
        "yazses.recimport.download._get", lambda url: pytest.fail("must not download")
    )
    config = types.SimpleNamespace(diarize=True, backend="sherpa", model_dir=str(tmp_path))
    assert build_diarizer(config) is None
    assert not list(tmp_path.iterdir())


def test_transcribe_help_does_not_promise_that_download():
    text = " ".join((cli.transcribe.__doc__ or "").split())
    assert "first run downloads" not in text
    assert "a diarized run does not download them" in text
    assert "--download-models" in text
