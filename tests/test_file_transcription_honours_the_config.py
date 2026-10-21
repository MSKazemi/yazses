"""Every file-transcription entry point decodes with the user's settings.

The bug this file was opened for: the MCP server's ``transcribe`` tool handed the
*whole* ``Config`` to ``recimport.pipeline.transcribe_file``, which expects the
``[recimport]`` section. ``getattr(config, "model", "")`` on a ``Config`` is ``""`` and
``getattr(config, "language", "en")`` is ``"en"``, so every call decoded with the
pipeline's hard-coded ``small.en`` in English -- whatever ``[stt]`` and ``[recimport]``
said -- and ``getattr(config, "diarize", False)`` meant the tool's own ``diarize``
argument could never label a speaker. Nothing raised: duck typing turned a wrong
argument into a confident default.

The audit around it found the same shape one level down: the pipeline's engine builder
fell back to ``small.en`` rather than inheriting ``[stt] model`` (which the
``[recimport]``/``[meeting]`` docs promise), so ``yazses meeting recover`` decoded with
a model the user never chose; and it built the decoder with neither ``[stt] device`` nor
``[stt] compute_type`` on any file path.

The decoder is replaced by a recorder installed in ``sys.modules``, so nothing here
needs faster-whisper, a model download, or a microphone.
"""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import numpy as np
import pytest

from yazses.config import Config, MeetingConfig, RecimportConfig, SttConfig


class _Recorder:
    """A fake decoder factory: records what it was built with, decodes to fixed text."""

    built: list[dict] = []

    def __init__(self, **kwargs):
        _Recorder.built.append(kwargs)
        self._language = kwargs.get("language", "en")

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "hello there", []


@pytest.fixture
def recorder(monkeypatch):
    _Recorder.built = []
    monkeypatch.setitem(
        sys.modules, "yazses.stt.faster_whisper",
        types.SimpleNamespace(FasterWhisperEngine=_Recorder),
    )
    # Audio with a real noise floor, so the silent-input path is not what is tested.
    rng = np.random.default_rng(0)
    signal = (rng.standard_normal(16000) * 1e-2).astype("float32")
    monkeypatch.setattr(
        "yazses.recimport.audio_io.load_audio", lambda *_a, **_k: (signal, 16000))
    return _Recorder


def _user_config() -> Config:
    """A user who chose everything a decoder can be told, and nothing default."""
    cfg = Config()
    cfg.stt = SttConfig(
        model="medium", language="de", device="cuda", compute_type="float32",
        cpu_threads=4, beam_size=1, condition_on_previous_text=False,
    )
    cfg.recimport = RecimportConfig(language="fa", model="")
    return cfg


# --- the reported bug: the MCP `transcribe` tool --------------------------------


def _mcp_transcribe(cfg, monkeypatch, diarizers=None, **arguments):
    from yazses.mcp.server import build_tools

    seen = diarizers if diarizers is not None else []
    monkeypatch.setattr(
        "yazses.recimport.pipeline.build_diarizer",
        lambda config: seen.append(config) or None,
    )
    tool = next(t for t in build_tools(cfg) if t.name == "transcribe")
    return tool.run(path="clip.wav", **arguments)


def test_mcp_transcribe_decodes_with_the_users_model_and_language(recorder, monkeypatch):
    assert _mcp_transcribe(_user_config(), monkeypatch) == "hello there"
    (built,) = recorder.built
    # `[recimport] model = ""` inherits `[stt] model`; the language is the section's.
    assert built["model_name"] == "medium"
    assert built["language"] == "fa"


def test_mcp_transcribe_decodes_on_the_users_device_and_precision(recorder, monkeypatch):
    _mcp_transcribe(_user_config(), monkeypatch)
    (built,) = recorder.built
    assert built["device"] == "cuda"
    assert built["compute_type"] == "float32"
    assert built["cpu_threads"] == 4
    assert built["beam_size"] == 1
    assert built["condition_on_previous_text"] is False


def test_mcp_diarize_argument_reaches_the_diarizer(recorder, monkeypatch):
    """`diarize=true` was unreachable: the diarizer read `diarize` off a whole Config."""
    seen: list = []
    _mcp_transcribe(_user_config(), monkeypatch, diarizers=seen, diarize=True)
    (config,) = seen
    assert config.diarize is True
    assert config.backend == "sherpa", "the [recimport] section, not the whole Config"


def test_mcp_without_diarize_follows_the_config(recorder, monkeypatch):
    cfg = _user_config()
    cfg.recimport.diarize = True
    seen: list = []
    _mcp_transcribe(cfg, monkeypatch, diarizers=seen)
    assert seen[0].diarize is True


# --- the same shape one level down: the pipeline's own engine builder -----------


def test_transcribe_file_refuses_a_whole_config():
    """The root cause, made loud: a Config where a section belongs must not decode."""
    from yazses.recimport.pipeline import transcribe_file

    with pytest.raises(TypeError, match=r"\[recimport\]"):
        transcribe_file(None, Config(), audio=np.zeros(10, dtype="float32"))


@pytest.mark.parametrize("section", [RecimportConfig(), MeetingConfig()])
def test_an_empty_section_model_inherits_the_stt_model(recorder, section):
    """`meeting recover` passes `[meeting]`, whose `model = ""` documents "inherit"."""
    from yazses.recimport.pipeline import _build_engine

    _build_engine(section, stt=SttConfig(model="small"))
    assert recorder.built[0]["model_name"] == "small"


def test_meeting_recover_decodes_with_the_stt_model(recorder, monkeypatch, tmp_path):
    """End to end through `recover_meeting`, the way `yazses meeting recover` calls it."""
    import yazses.meeting.recover as recover_mod

    def stop(_config):
        # Reached after the engine is built and has decoded: everything after it is
        # output writing, which other files test.
        raise RuntimeError("stop after the engine is built")

    monkeypatch.setattr("yazses.recimport.pipeline.build_diarizer", stop)
    monkeypatch.setattr(
        "yazses.meeting.session.read_wav_mono_f32",
        lambda *_a, **_k: np.zeros(16, dtype="float32"))
    for name in ("write_live_transcript", "archive_outputs"):
        monkeypatch.setattr(f"yazses.meeting.store.{name}", lambda *_a, **_k: None)
    monkeypatch.setattr("yazses.meeting.store.live_word_count", lambda *_a, **_k: 0)
    monkeypatch.setattr("yazses.meeting.store.read_meta", lambda *_a, **_k: {"id": "m"})
    cfg = _user_config()
    with pytest.raises(RuntimeError, match="stop after"):
        recover_mod.recover_meeting(tmp_path, cfg.meeting, stt=cfg.stt)
    built = recorder.built[0]
    assert built["model_name"] == "medium"
    assert (built["device"], built["compute_type"]) == ("cuda", "float32")


def test_an_explicit_section_model_wins(recorder):
    from yazses.recimport.pipeline import _build_engine

    _build_engine(RecimportConfig(model="large-v3"), stt=SttConfig(model="small"))
    assert recorder.built[0]["model_name"] == "large-v3"


def test_the_defaults_still_decode_the_shipped_model_on_cpu_int8(recorder):
    from yazses.recimport.pipeline import _build_engine

    _build_engine(RecimportConfig())
    built = recorder.built[0]
    assert (built["model_name"], built["language"]) == ("base.en", "en")
    assert (built["device"], built["compute_type"]) == ("cpu", "int8")


def test_yazses_transcribe_cli_uses_the_stt_device_and_precision(recorder, monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from yazses import cli

    cfg = _user_config()
    monkeypatch.setattr(cli, "load_config", lambda *_a, **_k: cfg, raising=False)
    monkeypatch.setattr("yazses.config.load_config", lambda *_a, **_k: cfg, raising=False)
    monkeypatch.setattr("yazses.recimport.pipeline.build_diarizer", lambda *_a, **_k: None)
    f = tmp_path / "clip.wav"
    f.write_bytes(b"RIFF")
    result = CliRunner().invoke(cli.app, ["transcribe", str(f)], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    built = recorder.built[0]
    assert built["model_name"] == "medium"
    assert built["language"] == "fa"
    assert (built["device"], built["compute_type"]) == ("cuda", "float32")


# --- the wrappers the daemon's factory applies ----------------------------------


def test_chinese_script_wraps_the_file_engine(recorder, monkeypatch):
    from yazses.recimport.pipeline import _build_engine

    monkeypatch.setattr(
        "yazses.postprocess.han_script.build_han_normaliser",
        lambda stt: (lambda text: f"[{getattr(stt, 'chinese_script', '')}]{text}"),
    )
    engine = _build_engine(
        RecimportConfig(language="zh", model="small"),
        stt=SttConfig(chinese_script="simplified"),
    )
    assert engine.transcribe_words(np.zeros(4, dtype="float32"))[0] == "[simplified]hello there"


def test_the_han_warning_reads_the_file_model_not_the_dictation_model(recorder, monkeypatch, caplog):
    """A `base.en` dictation model must not warn about a `small` file decode."""
    from yazses.recimport.pipeline import _build_engine

    monkeypatch.setattr(
        "yazses.postprocess.han_script.build_han_normaliser", lambda stt: (lambda t: t))
    with caplog.at_level("WARNING"):
        _build_engine(
            RecimportConfig(language="zh", model="small"),
            stt=SttConfig(model="base.en", chinese_script="simplified"),
        )
    assert "English-only" not in caplog.text


def test_persian_normalisation_follows_the_file_language(recorder):
    from yazses.recimport.pipeline import _build_engine

    stt = SttConfig(language="en", persian_normalisation=True)
    on = _build_engine(RecimportConfig(language="fa", model="small"), stt=stt)
    off = _build_engine(RecimportConfig(language="en", model="small"), stt=stt)
    assert type(on).__name__ == "_PersianNormaliserEngine"
    assert type(off).__name__ == "_Recorder"


# --- the shared helper itself (pure) --------------------------------------------


def test_helper_translate_auto_detects_the_source():
    from yazses.stt.decoder_settings import file_decoder_settings

    s = file_decoder_settings(SttConfig(), RecimportConfig(language="translate", model="small"))
    assert (s.language, s.task) == ("", "translate")


def test_helper_never_inherits_another_engines_checkpoint():
    """`[stt] model` may name a Parakeet/Moonshine model this Whisper-only path cannot load."""
    from yazses.stt.decoder_settings import file_decoder_settings

    for model in ("nemo-parakeet-tdt-0.6b-v2", "moonshine/base"):
        s = file_decoder_settings(SttConfig(model=model), RecimportConfig())
        assert s.model == "base.en"
        assert any(model in p for p in s.problems)


def test_helper_reports_an_english_only_model_for_a_foreign_language():
    from yazses.stt.decoder_settings import file_decoder_settings

    s = file_decoder_settings(SttConfig(), RecimportConfig(language="fa", model="small.en"))
    assert s.problems


def test_helper_rejects_a_whole_config_in_either_slot():
    from yazses.stt.decoder_settings import file_decoder_settings

    with pytest.raises(TypeError):
        file_decoder_settings(SttConfig(), Config())
    with pytest.raises(TypeError):
        file_decoder_settings(Config(), RecimportConfig())


def test_helper_accepts_duck_typed_sections():
    from yazses.stt.decoder_settings import file_decoder_settings

    s = file_decoder_settings(SimpleNamespace(), SimpleNamespace(language="fa", model="small"))
    assert (s.model, s.language, s.device, s.compute_type) == ("small", "fa", "cpu", "int8")
