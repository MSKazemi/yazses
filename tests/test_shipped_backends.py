"""The two backends that used to be selectable-but-unshipped (#70, #71).

``[voiceprint] backend = "resemblyzer"`` and ``[recimport]/[meeting] backend =
"pyannote"`` were accepted by config and reported by ``system/backends.py`` as
*not implemented in this build*. These tests cover the adapters that make them
real, and — just as importantly — that each now names **its own** extra when the
dependency is missing, since a wrong extra sends the user after a package that
cannot supply the backend they picked.

Everything here runs with neither optional dependency installed: the third-party
modules are faked through ``sys.modules``, which is how the existing denoise
tests exercise their lazy import. The one test that needs the real encoder is
skipped unless it is present.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types

import numpy as np
import pytest

from yazses.recimport.diarizer import DiarTurn
from yazses.voiceprint.embedding import cosine_similarity

# --------------------------------------------------------------------------
# Resemblyzer (#70)
# --------------------------------------------------------------------------

class _VpCfg:
    enabled = True
    backend = "resemblyzer"
    enroll_seconds = 25.0


def _fake_resemblyzer(monkeypatch, *, embed_vector=None, preprocessed=None):
    """Install a fake ``resemblyzer`` package and return the call log."""
    calls: dict[str, object] = {"embed_utterance": 0, "preprocess_sr": []}

    class _Encoder:
        device = "cpu"

        def __init__(self, device=None, verbose=True, weights_fpath=None):
            calls["device"] = device

        def embed_utterance(self, wav, **kw):
            calls["embed_utterance"] = int(calls["embed_utterance"]) + 1
            calls["embed_len"] = len(wav)
            return np.ones(256, dtype="float32") if embed_vector is None else embed_vector

    def _preprocess(buf, source_sr=None):
        calls["preprocess_sr"].append(source_sr)  # type: ignore[union-attr]
        if preprocessed is not None:
            return preprocessed
        return np.asarray(buf, dtype="float32")

    pkg = types.ModuleType("resemblyzer")
    pkg.VoiceEncoder = _Encoder
    pkg.preprocess_wav = _preprocess
    pkg.sampling_rate = 16000
    audio_mod = types.ModuleType("resemblyzer.audio")
    audio_mod.wav_to_mel_spectrogram = lambda wav: np.zeros((len(wav) // 160, 40), "float32")
    pkg.audio = audio_mod
    monkeypatch.setitem(sys.modules, "resemblyzer", pkg)
    monkeypatch.setitem(sys.modules, "resemblyzer.audio", audio_mod)
    return calls


def test_factory_builds_the_resemblyzer_backend(monkeypatch):
    """The name in config now reaches a real adapter instead of returning None."""
    _fake_resemblyzer(monkeypatch)
    from yazses.voiceprint.factory import build_embedder

    embedder = build_embedder(_VpCfg())
    assert embedder is not None
    assert embedder.name == "resemblyzer"


def test_resemblyzer_asks_for_cpu_explicitly(monkeypatch):
    """VoiceEncoder defaults to CUDA when torch sees a GPU; this project is CPU-only."""
    calls = _fake_resemblyzer(monkeypatch)
    from yazses.voiceprint.factory import build_embedder

    build_embedder(_VpCfg())
    assert calls["device"] == "cpu"


def test_long_audio_uses_embed_utterance(monkeypatch):
    calls = _fake_resemblyzer(monkeypatch)
    from yazses.voiceprint.factory import build_embedder

    embedder = build_embedder(_VpCfg())
    embedder.embed(np.ones(16000 * 2, dtype="float32"))  # 2 s > one 1.6 s partial
    assert calls["embed_utterance"] == 1


def test_short_audio_bypasses_the_zero_padding_path(monkeypatch):
    """A 500 ms Cocktail-Filter window must not be padded to 1.6 s with silence.

    ``embed_utterance`` pads short input unconditionally — there is no flag to
    turn it off — so the adapter has to take a different path, not a different
    argument. This is the regression that would silently return an embedding of
    1.1 s of digital silence mixed with the speaker.
    """
    calls = _fake_resemblyzer(monkeypatch)
    from yazses.voiceprint.factory import build_embedder

    embedder = build_embedder(_VpCfg())
    taken: list[int] = []
    monkeypatch.setattr(
        embedder, "_embed_short",
        lambda wav: taken.append(len(wav)) or np.ones(256, dtype="float32"),
    )
    embedder.embed(np.ones(8000, dtype="float32"))  # 0.5 s at 16 kHz

    assert calls["embed_utterance"] == 0, "short frame was zero-padded by embed_utterance"
    assert taken == [8000], "the short path must see the frame at its real length"


def test_resample_is_requested_only_when_the_rate_differs(monkeypatch):
    """Passing source_sr at 16 kHz sends every gate window through librosa for nothing."""
    calls = _fake_resemblyzer(monkeypatch)
    from yazses.voiceprint.factory import build_embedder

    embedder = build_embedder(_VpCfg())
    embedder.embed(np.ones(16000 * 2, dtype="float32"), sample_rate=16000)
    embedder.embed(np.ones(16000 * 2, dtype="float32"), sample_rate=48000)
    assert calls["preprocess_sr"] == [None, 48000]


def test_silence_trimmed_to_nothing_yields_a_droppable_embedding(monkeypatch):
    """preprocess_wav's VAD trim can empty a window; that must not become a match.

    A zero vector is the honest answer because cosine_similarity defines it as
    0.0, so the Cocktail Filter drops the window instead of matching it.
    """
    _fake_resemblyzer(monkeypatch, preprocessed=np.array([], dtype="float32"))
    from yazses.voiceprint.factory import build_embedder

    embedder = build_embedder(_VpCfg())
    emb = embedder.embed(np.zeros(8000, dtype="float32"))
    assert emb.vector.shape == (256,)
    assert cosine_similarity(emb.vector, np.ones(256)) == 0.0


def test_missing_resemblyzer_names_its_own_extra():
    """Not the `voiceprint` extra — that one ships speechbrain and cannot help."""
    from yazses.system.backends import probe_backend

    status = probe_backend(
        "resemblyzer",
        adapter="yazses.voiceprint.resemblyzer_backend",
        requires=("resemblyzer",),
        extra="voiceprint-resemblyzer",
        missing=lambda mods: [m for m in mods if m == "resemblyzer"],
    )
    assert status.implemented, "the adapter ships now; only the dependency is optional"
    assert "voiceprint-resemblyzer" in status.message


# --------------------------------------------------------------------------
# pyannote (#71)
# --------------------------------------------------------------------------

class _DiarCfg:
    diarize = True
    backend = "pyannote"
    min_speakers = 0
    max_speakers = 0


class _Segment:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class _Annotation:
    def __init__(self, tracks):
        self._tracks = tracks

    def itertracks(self, yield_label=False):
        for start, end, label in self._tracks:
            yield _Segment(start, end), None, label


def _fake_pyannote(monkeypatch, tracks, *, pipeline_is_none=False):
    """Install fake ``torch`` and ``pyannote.audio`` modules; return the call log."""
    calls: dict[str, object] = {}

    class _Pipeline:
        def to(self, device):
            return self

        def __call__(self, payload, **kw):
            calls["payload_sr"] = payload["sample_rate"]
            calls["kwargs"] = kw
            return _Annotation(tracks)

    class _PipelineFactory:
        @staticmethod
        def from_pretrained(name, use_auth_token=None):
            calls["model"] = name
            calls["token"] = use_auth_token
            return None if pipeline_is_none else _Pipeline()

    torch_mod = types.ModuleType("torch")
    torch_mod.device = lambda name: name
    torch_mod.from_numpy = lambda a: a

    class _NoGrad:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            return False

    torch_mod.no_grad = _NoGrad
    monkeypatch.setitem(sys.modules, "torch", torch_mod)

    pkg = types.ModuleType("pyannote")
    audio_mod = types.ModuleType("pyannote.audio")
    audio_mod.Pipeline = _PipelineFactory
    pkg.audio = audio_mod
    monkeypatch.setitem(sys.modules, "pyannote", pkg)
    monkeypatch.setitem(sys.modules, "pyannote.audio", audio_mod)
    return calls


def test_factory_builds_the_pyannote_diarizer(monkeypatch):
    _fake_pyannote(monkeypatch, [(0.0, 1.0, "SPEAKER_00")])
    from yazses.recimport.factory import build_diarizer

    assert build_diarizer(_DiarCfg()) is not None


def test_pyannote_labels_are_normalised_to_the_sherpa_shape(monkeypatch):
    """Downstream naming/alignment key off ``speaker_<n>``, not ``SPEAKER_00``.

    Passing pyannote's own labels through would silently change every label in a
    stored transcript when a user switches backend, and break voiceprint naming.
    Numbering follows first appearance so it reads naturally in a transcript.
    """
    _fake_pyannote(
        monkeypatch,
        [(0.0, 1.0, "SPEAKER_03"), (1.0, 2.0, "SPEAKER_01"), (2.0, 3.0, "SPEAKER_03")],
    )
    from yazses.recimport.factory import build_diarizer

    turns = build_diarizer(_DiarCfg()).diarize(np.zeros(16000, dtype="float32"))
    assert [t.speaker for t in turns] == ["speaker_0", "speaker_1", "speaker_0"]
    assert all(isinstance(t, DiarTurn) for t in turns)


def test_pyannote_turns_are_sorted_by_start(monkeypatch):
    _fake_pyannote(
        monkeypatch, [(5.0, 6.0, "SPEAKER_00"), (1.0, 2.0, "SPEAKER_01")]
    )
    from yazses.recimport.factory import build_diarizer

    turns = build_diarizer(_DiarCfg()).diarize(np.zeros(16000, dtype="float32"))
    assert [t.start for t in turns] == [1.0, 5.0]


@pytest.mark.parametrize(
    ("min_s", "max_s", "expected"),
    [
        (0, 0, {}),                                  # auto-detect, the default
        (2, 0, {"min_speakers": 2}),
        (0, 4, {"max_speakers": 4}),
        (3, 5, {"min_speakers": 3, "max_speakers": 5}),
        (3, 3, {"num_speakers": 3}),                 # known exactly
    ],
)
def test_speaker_bounds_translate_the_zero_means_auto_convention(
    monkeypatch, min_s, max_s, expected
):
    """pyannote rejects a redundant equal min/max pair; it wants num_speakers."""
    calls = _fake_pyannote(monkeypatch, [(0.0, 1.0, "SPEAKER_00")])
    from yazses.recimport.factory import build_diarizer

    cfg = _DiarCfg()
    cfg.min_speakers, cfg.max_speakers = min_s, max_s
    build_diarizer(cfg).diarize(np.zeros(16000, dtype="float32"))
    assert calls["kwargs"] == expected


def test_a_gated_model_without_a_token_explains_the_two_fixes(monkeypatch):
    """from_pretrained returns None (not raises) for a gated repo — say why."""
    _fake_pyannote(monkeypatch, [], pipeline_is_none=True)
    from yazses.recimport.pyannote_backend import PyannoteDiarizer

    with pytest.raises(RuntimeError) as excinfo:
        PyannoteDiarizer(_DiarCfg())
    message = str(excinfo.value)
    assert "conditions" in message and "HF_TOKEN" in message


def test_the_backend_is_dormant_without_the_dependency(monkeypatch):
    """No pyannote installed → a plain transcript, never a crash."""
    monkeypatch.setitem(sys.modules, "pyannote.audio", None)
    from yazses.recimport.factory import build_diarizer

    monkeypatch.delitem(sys.modules, "yazses.recimport.pyannote_backend", raising=False)
    assert build_diarizer(_DiarCfg()) is None


def test_pyannote_telemetry_is_disabled_before_the_package_is_imported(monkeypatch):
    """ADR-011 regression guard: pyannote.audio 4.x tracks usage by DEFAULT.

    Its bundled telemetry/config.yaml sets ``metrics_enabled: true`` and an OTLP
    endpoint at pyannote.ai, and ``track_pipeline_apply`` reports the *duration*
    of the audio being diarized. The kill-switch only works if the environment
    variable is set before import, because upstream defaults it from the config
    file ``if "PYANNOTE_METRICS_ENABLED" not in os.environ`` — so this asserts
    the ordering, not merely the final value.
    """
    seen_at_import: list[str | None] = []

    class _WatchfulPipelineFactory:
        @staticmethod
        def from_pretrained(name, use_auth_token=None):
            seen_at_import.append(os.environ.get("PYANNOTE_METRICS_ENABLED"))
            return _StubPipeline()

    class _StubPipeline:
        def to(self, device):
            return self

    _fake_pyannote(monkeypatch, [])
    torch_mod = sys.modules["torch"]
    audio_mod = types.ModuleType("pyannote.audio")
    audio_mod.Pipeline = _WatchfulPipelineFactory
    monkeypatch.setitem(sys.modules, "pyannote.audio", audio_mod)
    monkeypatch.setattr(torch_mod, "device", lambda n: n, raising=False)
    monkeypatch.delenv("PYANNOTE_METRICS_ENABLED", raising=False)

    from yazses.recimport.pyannote_backend import PyannoteDiarizer

    PyannoteDiarizer(_DiarCfg())
    assert seen_at_import == ["false"], (
        "telemetry must already be off when pyannote is first touched"
    )


def test_telemetry_is_disabled_even_if_the_user_exported_it_on():
    """An env var set by another tool is not consent to transmit dictation metadata."""
    from yazses.recimport.pyannote_backend import _disable_upstream_telemetry

    env = {"PYANNOTE_METRICS_ENABLED": "true"}
    _disable_upstream_telemetry(env)
    assert env["PYANNOTE_METRICS_ENABLED"] == "false"


def test_missing_pyannote_names_its_own_extra():
    """Not the `diarization` extra — that one ships sherpa-onnx and cannot help."""
    from yazses.system.backends import probe_backend

    status = probe_backend(
        "pyannote",
        adapter="yazses.recimport.pyannote_backend",
        requires=("pyannote.audio",),
        extra="diarization-pyannote",
        missing=lambda mods: [m for m in mods if m == "pyannote.audio"],
    )
    assert status.implemented, "the adapter ships now; only the dependency is optional"
    assert "diarization-pyannote" in status.message


# --------------------------------------------------------------------------
# Real-dependency check (skipped unless the extra is actually installed)
# --------------------------------------------------------------------------

@pytest.mark.skipif(
    importlib.util.find_spec("resemblyzer") is None,
    reason="the voiceprint-resemblyzer extra is not installed",
)
def test_real_resemblyzer_returns_a_unit_vector_at_both_lengths():
    """Both paths must produce the same kind of object: a 256-d L2-normed vector.

    The short path reimplements what embed_utterance does for one partial, so
    this pins that it did not drift into returning an unnormalised embedding —
    which would still "work" but silently change every cosine threshold.
    """
    from yazses.voiceprint.resemblyzer_backend import ResemblyzerEmbedder

    embedder = ResemblyzerEmbedder(_VpCfg())
    rng = np.random.default_rng(0)
    speech = rng.normal(0, 0.1, 16000 * 2).astype("float32")

    for samples in (8000, 16000 * 2):  # short path, then embed_utterance
        vector = embedder.embed(speech[:samples]).vector
        assert vector.shape == (256,)
        assert np.isfinite(vector).all()
        assert abs(float(np.linalg.norm(vector)) - 1.0) < 1e-3
