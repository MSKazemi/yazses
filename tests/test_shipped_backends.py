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

from tests.decoder_stack import needs_huggingface_hub
from yazses.recimport.diarizer import DiarTurn
from yazses.system.deps import missing_modules
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


#: Distinguishes "no override" from an override of ``None`` -- ``None`` is a real
#: thing a pipeline could hand back and is exactly what the guard must reject.
_UNSET = object()


def _fake_pyannote(monkeypatch, tracks, *, pipeline_is_none=False, raises=None,
                   result=_UNSET):
    """Install fake ``torch`` and ``pyannote.audio`` modules; return the call log.

    ``raises`` makes ``from_pretrained`` raise instead of returning, which is what
    huggingface_hub actually does when ``token=True`` finds no stored token — the
    path that reaches a real user first.
    """
    calls: dict[str, object] = {}

    class _Pipeline:
        def to(self, device):
            return self

        def __call__(self, payload, **kw):
            calls["payload_sr"] = payload["sample_rate"]
            calls["kwargs"] = kw
            return _Annotation(tracks) if result is _UNSET else result

    class _PipelineFactory:
        @staticmethod
        def from_pretrained(name, token=None):
            calls["model"] = name
            calls["token"] = token
            if raises is not None:
                raise raises
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


def test_a_pipeline_that_returns_no_annotation_fails_by_name(monkeypatch):
    """pyannote's `Pipeline.__call__` is typed as returning its result *or* an
    iterator, because it also accepts an iterable of files. Only the first has
    `itertracks`. Reading turns off the other one raises `AttributeError` from
    inside a loop -- during a meeting's post-pass, which runs after the recording
    has been consumed and long after the user walked away. Say what happened
    instead."""
    _fake_pyannote(monkeypatch, [], result=iter([]))

    from yazses.recimport.pyannote_backend import PyannoteDiarizer

    diarizer = PyannoteDiarizer(_DiarCfg())
    with pytest.raises(RuntimeError) as excinfo:
        diarizer.diarize(np.zeros(16000, dtype="float32"))
    assert "itertracks" in str(excinfo.value)


def test_a_normal_pipeline_result_still_produces_turns(monkeypatch):
    """The guard must not reject the shape that actually ships."""
    _fake_pyannote(monkeypatch, [(0.0, 1.0, "SPEAKER_00")])

    from yazses.recimport.pyannote_backend import PyannoteDiarizer

    turns = PyannoteDiarizer(_DiarCfg()).diarize(np.zeros(16000, dtype="float32"))
    assert [t.speaker for t in turns] == ["speaker_0"]


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


def _assert_names_the_whole_remedy(message):
    """Both gated repos, the acceptance step, and a way to authenticate."""
    from yazses.recimport.pyannote_backend import PIPELINE_ID, SEGMENTATION_ID

    assert "conditions" in message, message
    assert PIPELINE_ID in message, message
    # The near-miss this exists for: accepting the pipeline and not the
    # segmentation model it loads, which fails with an error naming neither.
    assert SEGMENTATION_ID in message, message
    assert "HF_TOKEN" in message and "hf auth login" in message, message


def test_a_gated_model_without_a_token_explains_the_two_fixes(monkeypatch):
    """from_pretrained returns None (not raises) for some gated cases — say why."""
    _fake_pyannote(monkeypatch, [], pipeline_is_none=True)
    from yazses.recimport.pyannote_backend import PyannoteDiarizer

    with pytest.raises(RuntimeError) as excinfo:
        PyannoteDiarizer(_DiarCfg())
    _assert_names_the_whole_remedy(str(excinfo.value))


# Each of these is a real shape huggingface_hub answers a gated repo with. The
# first is the one every new user hits: `_auth_token()` returns True to use the
# stored login, and hub raises rather than returning None when there is none.
@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("LocalTokenNotFoundError", "Token is required (`token=True`), but no token found."),
        ("GatedRepoError", "403 Client Error. Access to model is restricted."),
        ("RepositoryNotFoundError", "401 Client Error. Repository Not Found"),
        ("HfHubHTTPError", "Your request to access model is awaiting a review"),
    ],
)
def test_a_raised_access_failure_gets_the_same_remedy(monkeypatch, name, text):
    """The remedy used to be unreachable whenever hub raised instead of returning.

    A user with no token saw huggingface_hub's own text, which names the token
    and never the acceptance — so the message read as if the token were wrong.
    """
    exc = type(name, (OSError,), {})(text)
    _fake_pyannote(monkeypatch, [], raises=exc)
    from yazses.recimport.pyannote_backend import PyannoteDiarizer

    with pytest.raises(RuntimeError) as excinfo:
        PyannoteDiarizer(_DiarCfg())
    _assert_names_the_whole_remedy(str(excinfo.value))
    # The original text is kept, not swallowed: it is the only part that says
    # which of the several access failures this actually was.
    assert text in str(excinfo.value)
    assert excinfo.value.__cause__ is exc


def test_a_failure_that_is_not_about_access_is_not_relabelled(monkeypatch):
    """A disk or network fault must not be reported as a licence problem.

    The predicate is deliberately narrow: telling someone to accept model
    conditions when their disk is full sends them to a web page for an hour.
    """
    exc = OSError("No space left on device")
    _fake_pyannote(monkeypatch, [], raises=exc)
    from yazses.recimport.pyannote_backend import PyannoteDiarizer

    with pytest.raises(OSError) as excinfo:
        PyannoteDiarizer(_DiarCfg())
    assert excinfo.value is exc
    assert "conditions" not in str(excinfo.value)


@needs_huggingface_hub
def test_the_predicate_binds_against_the_real_huggingface_error_classes():
    """The names are matched as strings — so prove they are still the real names.

    ``huggingface_hub`` ships with ``faster_whisper``, so it is always installed
    even without the diarization extra. Matching on the type name rather than
    importing the classes keeps this adapter importable without the extra, but it
    means an upstream rename would silently turn the remedy back into the raw
    error. This is what notices.
    """
    from huggingface_hub import errors

    from yazses.recimport.pyannote_backend import (
        _ACCESS_ERROR_TYPES,
        _is_access_failure,
    )

    for name in _ACCESS_ERROR_TYPES:
        cls = getattr(errors, name, None)
        assert cls is not None, f"huggingface_hub.errors no longer has {name}"
        assert _is_access_failure(cls.__new__(cls))


def test_the_login_command_is_the_one_that_still_exists():
    """`huggingface-cli` is a deprecation shim in huggingface_hub 1.x.

    Naming it first sends a user to a command that prints a deprecation notice
    today and will not exist at all in the version this project already depends
    on. The old spelling stays in the message only as a parenthetical for people
    on an older hub.
    """
    from yazses.recimport.pyannote_backend import _gated_model_error

    message = str(_gated_model_error())
    assert message.index("hf auth login") < message.index("huggingface-cli login")


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
        def from_pretrained(name, token=None):
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

@needs_huggingface_hub
@pytest.mark.skipif(
    # NOT `find_spec("pyannote.audio")` — that raises ModuleNotFoundError at
    # collection time when `pyannote` is absent, which is the very bug this PR
    # fixes in `missing_modules`. Use the fixed helper, which also dogfoods it.
    bool(missing_modules(["pyannote.audio"])),
    reason="the diarization-pyannote extra is not installed",
)
def test_pyannote_adapter_call_binds_against_the_real_signature(monkeypatch):
    """A faked pipeline validates our *belief* about the API, not the API.

    This caught a real bug. pyannote 3.x took ``use_auth_token``; 4.x renamed it
    to ``token`` with **no alias and no ``**kwargs``**, so the old spelling is a
    ``TypeError`` at construction rather than a silently ignored argument. Every
    faked test passed anyway, because the fake accepted whatever it was handed.

    Checking that the *signature* contains ``token`` would not be enough — that
    passes even if the adapter goes back to the wrong spelling. So this replaces
    ``from_pretrained`` with a spy that **binds the adapter's actual call against
    the real signature**, failing on a wrong kwarg from either side. The spy
    returns ``None`` (upstream's own "gated repo" answer), so the adapter's
    RuntimeError is the success path. No token, no model, no network.
    """
    import inspect

    from pyannote.audio import Pipeline

    real_sig = inspect.signature(Pipeline.from_pretrained)
    seen: dict = {}

    def _spy(*args, **kwargs):
        real_sig.bind(*args, **kwargs)   # TypeError here = the adapter is wrong
        seen["kwargs"] = kwargs
        return None

    monkeypatch.setattr(Pipeline, "from_pretrained", _spy)

    from yazses.recimport.pyannote_backend import PyannoteDiarizer

    with pytest.raises(RuntimeError):    # gated-repo path, which is what None means
        PyannoteDiarizer(_DiarCfg())
    assert "token" in seen["kwargs"]


def _resemblyzer_import_error() -> str | None:
    """Why ``import resemblyzer`` fails here, or ``None`` when it works.

    ``find_spec`` is not enough, and this file was the proof: it answers whether
    the package is **on disk**, never whether it **imports**. Resemblyzer pulls in
    ``webrtcvad``, whose first line is ``import pkg_resources`` -- removed from
    setuptools in 81.0.0 -- so a *correctly installed* ``voiceprint-resemblyzer``
    extra raises ``ModuleNotFoundError`` on any current setuptools.

    That is the documented, expected state: the pin that used to hold setuptools
    below 81 was removed because ``uv.lock`` resolves one version for the whole
    workspace, so it held every install and both shipped bundles below a patched
    setuptools. `voiceprint/factory.py` names the remedy at the point of failure
    for exactly this reason.

    The test below therefore has to skip on it rather than fail -- it was gated on
    ``find_spec`` and so failed the moment the extra was installed, which is the
    mistake the module it tests documents in a comment.
    """
    if importlib.util.find_spec("resemblyzer") is None:
        return "the voiceprint-resemblyzer extra is not installed"
    try:
        importlib.import_module("resemblyzer")
    except Exception as exc:  # ImportError, but a C extension can raise anything
        return f"resemblyzer is installed but does not import here: {exc}"
    return None


@pytest.mark.skipif(
    _resemblyzer_import_error() is not None,
    reason=_resemblyzer_import_error() or "",
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


@pytest.mark.skipif(
    importlib.util.find_spec("resemblyzer") is None
    or _resemblyzer_import_error() is None,
    reason="needs the extra installed on a setuptools that dropped pkg_resources",
)
def test_a_resemblyzer_that_cannot_import_names_the_remedy_and_stays_dormant(caplog):
    """The state every user of this extra lands in on a current setuptools.

    `pkg_resources` is gone from setuptools 81+, so importing the backend raises
    three layers down with a message that names neither the extra nor the fix.
    `build_embedder` must turn that into the remedy and return None -- a dormant
    optional feature, not a crashed daemon.
    """
    from yazses.voiceprint.factory import build_embedder

    with caplog.at_level("WARNING"):
        assert build_embedder(_VpCfg()) is None

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "pkg_resources" in text, text
    assert 'setuptools<81' in text, (
        "the user is left with a bare ModuleNotFoundError from inside webrtcvad, "
        "which names neither the extra they installed nor the one-line fix."
    )

# --------------------------------------------------------------------------
# diarization_status must follow the configured backend (#71 integration)
# --------------------------------------------------------------------------

def test_status_probes_pyannote_not_sherpa_when_pyannote_is_configured(monkeypatch, tmp_path):
    """The readiness probe used to hard-code sherpa whatever was configured.

    Left as it was, a correctly-installed pyannote user would be told on every
    `meeting start` that their transcript would not be attributed — the exact
    false alarm this function exists to prevent. `ready` was unreachable for
    pyannote because the check literally read `backend == "sherpa"`.
    """
    from yazses.recimport import factory

    monkeypatch.setattr(factory, "_pyannote_model_cached", lambda: True)
    monkeypatch.setattr(
        "yazses.system.deps.missing_modules",
        lambda mods: [] if list(mods) == ["pyannote.audio"] else list(mods),
    )
    cfg = _DiarCfg()
    status = factory.diarization_status(cfg)
    assert status["backend"] == "pyannote"
    assert status["extra_installed"] is True
    assert status["ready"] is True, "pyannote can never be ready if sherpa is probed"


def test_status_reports_not_ready_when_the_gated_model_is_uncached(monkeypatch):
    """No cache means the first run must still fetch a gated repo — say so."""
    from yazses.recimport import factory

    monkeypatch.setattr(factory, "_pyannote_model_cached", lambda: False)
    monkeypatch.setattr(
        "yazses.system.deps.missing_modules",
        lambda mods: [] if list(mods) == ["pyannote.audio"] else list(mods),
    )
    status = factory.diarization_status(_DiarCfg())
    assert status["extra_installed"] is True
    assert status["models_present"] is False
    assert status["ready"] is False


def test_status_is_never_ready_for_backend_none():
    """`none` is a deliberate opt-out, not a half-configured state."""
    from yazses.recimport.factory import diarization_status

    cfg = _DiarCfg()
    cfg.backend = "none"
    status = diarization_status(cfg)
    assert status["ready"] is False
    assert status["extra_installed"] is False


def test_status_does_not_import_the_heavy_backend():
    """It runs on the `meeting status` path; it must not pull torch in."""
    import subprocess

    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; from yazses.recimport.factory import diarization_status;"
         "print([m for m in sys.modules if m.split('.')[0] in "
         "('pyannote','torch','sherpa_onnx')])"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out == "[]", f"heavy modules imported by the status path: {out}"
