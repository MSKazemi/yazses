"""Language/model compatibility guardrails for every non-English language (#515, FA-06).

Persian is the motivating case: `language = "fa"` beside an English-only checkpoint
does not fail. faster-whisper replaces the language with "en" for an English-only
tokenizer and logs it; Parakeet v2 and Moonshine take no language at all; and the
Distil-Whisper large checkpoints are English-only without a `.en` suffix, so the old
suffix-only guard let them through. The user got fluent English for Persian speech.

These tests pin: the capability table is data with a cited source per row and stays
in sync with the registries it describes; the pairing is reported by the config
loader, refused by the engine factory (before any model loads) and by Settings,
and shown by doctor/`language status`; and the default English install is unchanged.
No audio, no model, no network.
"""
from __future__ import annotations

import dataclasses
import logging

import pytest

from tests.decoder_stack import needs_faster_whisper
from yazses.config import Config, LatencyConfig, SttConfig, load_config_checked
from yazses.configcheck import ConfigProblem, language_pairing_problems
from yazses.language.capability import (
    CAPABILITIES,
    ENGINE_DEFAULT_MODELS,
    WHISPER_LANGUAGES,
    check,
    normalise_language,
)
from yazses.stt.download import WHISPER_MODELS, is_english_only, language_model_problem
from yazses.stt.errors import LanguageUnsupportedError, ModelUnavailableError

ENGLISH_ONLY_WHISPER = [
    "tiny.en", "base.en", "small.en", "medium.en",
    "distil-small.en", "distil-medium.en",
    "distil-large-v2", "distil-large-v3", "distil-large-v3.5",
]
MULTILINGUAL_WHISPER = [
    "tiny", "base", "small", "medium", "large", "large-v1", "large-v2", "large-v3",
    "large-v3-turbo", "turbo",
]


def _cfg(**stt) -> Config:
    cfg = Config()
    cfg.stt = SttConfig(**stt)
    return cfg


# ── the table is data, cited, and in sync with what it describes ─────────────

def test_every_row_cites_a_source():
    for cap in CAPABILITIES:
        assert cap.source_url.startswith("https://"), cap
        assert cap.evidence.strip(), cap
        assert cap.languages, cap


def test_every_known_whisper_name_has_a_row_and_no_row_is_invented():
    """Adding a model to `WHISPER_MODELS` without stating its languages fails here."""
    rows = {c.model for c in CAPABILITIES if c.engine == "faster-whisper"}
    assert rows == set(WHISPER_MODELS)


def test_whisper_language_codes_match_faster_whisper():
    tokenizer = pytest.importorskip("faster_whisper.tokenizer")
    assert WHISPER_LANGUAGES | {"yue"} == set(tokenizer._LANGUAGE_CODES)


def test_engine_defaults_match_the_engines():
    """The table must describe the checkpoint each engine actually loads."""
    from yazses.stt import moonshine, parakeet

    assert ENGINE_DEFAULT_MODELS == {
        "parakeet": parakeet.DEFAULT_MODEL,
        "moonshine": moonshine.DEFAULT_MODEL,
    }


@pytest.mark.parametrize("model", ENGLISH_ONLY_WHISPER)
def test_english_only_checkpoints_cannot_take_persian(model):
    support = check("faster-whisper", model, "fa")
    assert support.verdict == "unsupported"
    assert support.multilingual is False
    assert "English-only" in support.reason
    assert is_english_only(model)


@pytest.mark.parametrize("model", MULTILINGUAL_WHISPER)
def test_multilingual_checkpoints_take_persian(model):
    support = check("faster-whisper", model, "fa")
    assert support.verdict == "supported"
    assert support.multilingual is True
    assert not is_english_only(model)


def test_distil_large_is_named_without_en_but_is_english_only():
    """The gap the old suffix check had: no `.en`, English-only by its model card."""
    problem = language_model_problem("distil-large-v3", "fa")
    assert problem and "'large-v3'" in problem


@pytest.mark.parametrize("engine,model", [
    ("parakeet", ""),
    ("parakeet", "base.en"),  # a Whisper name: Parakeet loads its own default
    ("parakeet", "nemo-parakeet-tdt-0.6b-v2"),
    ("parakeet", "nemo-parakeet-tdt-0.6b-v3"),  # 25 European languages, not Persian
    ("moonshine", ""),
    ("moonshine", "moonshine/tiny"),
])
def test_non_whisper_engines_cannot_take_persian(engine, model):
    support = check(engine, model, "fa")
    assert support.verdict == "unsupported"
    assert "faster-whisper" in support.reason  # names the engine that can


def test_parakeet_v3_takes_a_language_its_card_lists():
    assert check("parakeet", "nemo-parakeet-tdt-0.6b-v3", "de").verdict == "supported"


def test_cantonese_needs_the_v3_tokenizer():
    assert check("faster-whisper", "large-v3", "yue").verdict == "supported"
    small = check("faster-whisper", "small", "yue")
    assert small.verdict == "unsupported" and "large-v3" in small.reason


def test_a_custom_checkpoint_is_unknown_never_refused():
    """Guessing would reject a fine-tuned Persian model that works."""
    support = check("faster-whisper", "someone/whisper-small-fa", "fa")
    assert support.verdict == "unknown"
    assert support.multilingual is None
    assert language_model_problem("someone/whisper-small-fa", "fa") is None


def test_a_custom_dot_en_checkpoint_is_still_english_only():
    assert check("faster-whisper", "/models/my-small.en", "fa").verdict == "unsupported"


@pytest.mark.parametrize("value,expected", [
    ("fa", "fa"), ("FA-IR", "fa"), ("fa_IR", "fa"), ("", ""), ("translate", ""), ("auto", ""),
])
def test_language_codes_are_normalised(value, expected):
    assert normalise_language(value) == expected


@pytest.mark.parametrize("engine", ["faster-whisper", "parakeet", "moonshine", "", "bogus"])
@pytest.mark.parametrize("language", ["", "en"])
def test_english_and_auto_detect_are_always_supported(engine, language):
    assert check(engine, "", language).verdict == "supported"


# ── English stays the default and is unchanged ───────────────────────────────

def test_default_config_is_english_and_supported():
    cfg = Config()
    assert (cfg.stt.engine, cfg.stt.model, cfg.stt.language) == ("faster-whisper", "base.en", "en")
    support = check(cfg.stt.engine, cfg.stt.model, cfg.stt.language)
    assert support.verdict == "supported"
    assert support.multilingual is False
    assert language_pairing_problems(cfg) == []


def test_an_existing_english_config_loads_with_no_new_problem(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[stt]\nmodel = "small.en"\nlanguage = "en"\n[latency]\nenabled = true\n',
        encoding="utf-8",
    )
    loaded = load_config_checked(path)
    assert loaded.problems == []
    assert loaded.config.stt.model == "small.en"


@needs_faster_whisper
def test_the_default_english_engine_is_built_exactly_as_before(monkeypatch):
    seen: dict = {}

    class _Fake:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    import yazses.stt.faster_whisper as fw
    from yazses.stt.factory import build_engine

    monkeypatch.setattr(fw, "FasterWhisperEngine", _Fake)
    build_engine(SttConfig())
    assert seen["model_name"] == "base.en"
    assert seen["language"] == "en"


# ── config validation reports it ─────────────────────────────────────────────

def test_configcheck_reports_persian_on_an_english_only_model(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[stt]\nmodel = "base.en"\nlanguage = "fa"\n', encoding="utf-8")
    problems = load_config_checked(path).problems
    assert len(problems) == 1
    (problem,) = problems
    assert (problem.section, problem.key) == ("stt", "model")
    assert problem.refused and not problem.repaired
    assert "'base'" in problem.detail and "refused" in problem.detail
    # Nothing is rewritten: swapping in a multilingual model is a download nobody asked for.
    assert load_config_checked(path).config.stt.model == "base.en"


def test_configcheck_names_the_engine_key_for_parakeet():
    (problem,) = language_pairing_problems(_cfg(engine="parakeet", language="fa"))
    assert problem.key == "engine"


def test_configcheck_reports_an_inert_light_model():
    cfg = _cfg(model="small", language="fa")
    cfg.latency = LatencyConfig(enabled=True, light_model="tiny.en")
    (problem,) = language_pairing_problems(cfg)
    assert (problem.section, problem.key) == ("latency", "light_model")
    assert "governor" in problem.detail


def test_configcheck_is_silent_for_a_supported_or_custom_pair():
    assert language_pairing_problems(_cfg(model="small", language="fa")) == []
    assert language_pairing_problems(_cfg(model="org/custom-fa", language="fa")) == []


def test_doctor_labels_a_refused_value_as_refused(tmp_path):
    from yazses.system.doctor import _config_validity

    path = tmp_path / "config.toml"
    path.write_text('[stt]\nmodel = "base.en"\nlanguage = "fa"\n', encoding="utf-8")
    rows = _config_validity(path)
    assert rows[0][1] == "FAIL" and "1 refused" in rows[0][2]
    assert rows[1][0] == "  └ refused"


# ── the engine factory refuses, before any model loads ──────────────────────

@pytest.fixture
def no_engine_loads(monkeypatch):
    """Fail the test if any engine class is constructed."""
    import yazses.stt.faster_whisper as fw

    def _boom(**kwargs):
        raise AssertionError(f"an engine was built: {kwargs}")

    monkeypatch.setattr(fw, "FasterWhisperEngine", _boom)


@pytest.mark.parametrize("stt", [
    SttConfig(model="base.en", language="fa"),
    SttConfig(model="distil-large-v3", language="fa"),
    SttConfig(engine="parakeet", model="base.en", language="fa"),
    SttConfig(engine="moonshine", model="moonshine/base", language="de"),
    SttConfig(engine="bogus", model="base.en", language="fa"),  # unknown → faster-whisper
])
@needs_faster_whisper
def test_factory_refuses_an_unsupported_pair(no_engine_loads, monkeypatch, stt):
    import builtins

    real_import = builtins.__import__

    def _guarded(name, *args, **kwargs):
        if name in ("yazses.stt.parakeet", "yazses.stt.moonshine"):
            raise AssertionError(f"{name} imported for a refused pairing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded)
    from yazses.stt.factory import build_engine

    with pytest.raises(LanguageUnsupportedError) as exc:
        build_engine(stt)
    # The daemon holds ModelUnavailableError in ERROR state with a toast (#310).
    assert isinstance(exc.value, ModelUnavailableError)


@needs_faster_whisper
def test_the_parakeet_fallback_cannot_rescue_a_language_into_english(monkeypatch, caplog):
    """v3 + German passes, its runtime is missing, and the fallback is `base.en`."""
    import builtins

    real_import = builtins.__import__

    def _missing(name, *args, **kwargs):
        if name == "yazses.stt.parakeet":
            raise ModuleNotFoundError("No module named 'onnx_asr'", name="onnx_asr")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _missing)
    from yazses.stt.factory import build_engine

    with pytest.raises(LanguageUnsupportedError) as exc:
        build_engine(SttConfig(engine="parakeet", model="nemo-parakeet-tdt-0.6b-v3",
                               language="de"))
    assert exc.value.model == "base.en"


@needs_faster_whisper
def test_factory_warns_but_builds_a_custom_checkpoint(monkeypatch, caplog):
    seen: dict = {}

    class _Fake:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    import yazses.stt.faster_whisper as fw
    from yazses.stt.factory import build_engine

    monkeypatch.setattr(fw, "FasterWhisperEngine", _Fake)
    with caplog.at_level(logging.WARNING, logger="yazses.stt.factory"):
        build_engine(SttConfig(model="someone/whisper-small-fa", language="fa"))
    assert seen["language"] == "fa"
    assert "cannot confirm" in caplog.text


@needs_faster_whisper
def test_the_latency_governor_keeps_the_base_engine_when_the_light_model_is_refused(
    monkeypatch,
):
    """Without the refusal, the governor would switch Persian dictation to `tiny.en`."""
    from yazses.latency.pool import EnginePool
    from yazses.stt.factory import build_engine

    class _Fake:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    import yazses.stt.faster_whisper as fw

    monkeypatch.setattr(fw, "FasterWhisperEngine", _Fake)
    stt = SttConfig(model="small", language="fa")
    base = build_engine(stt)
    pool = EnginePool(
        lambda model, beam: build_engine(dataclasses.replace(stt, model=model, beam_size=beam)),
        ("small", 0), base, spawn=lambda fn: fn(),
    )
    assert pool.get("tiny.en", 2) is None
    assert pool.resident() == (("small", 0),)


def test_the_toast_fits_a_windows_balloon():
    exc = LanguageUnsupportedError("faster-whisper", "distil-large-v3.5", "fa", "reason")
    title, body = exc.notification()
    assert len(body) < 256 and "yazses language status" in body
    assert "distil-large-v3.5" in str(exc)


@needs_faster_whisper
def test_file_transcription_refuses_too(no_engine_loads):
    from yazses.config import RecimportConfig
    from yazses.recimport.pipeline import _build_engine

    with pytest.raises(LanguageUnsupportedError):
        _build_engine(RecimportConfig(model="small.en", language="fa"))


# ── Settings cannot save it ──────────────────────────────────────────────────

def test_settings_refuses_persian_while_the_engine_is_parakeet():
    from yazses.settingsui.controller import SettingsController

    writes: list = []
    cfg = _cfg(engine="parakeet", model="small", language="en")
    controller = SettingsController(
        load_config=lambda: cfg,
        writer=lambda section, key, value, quote: writes.append((section, key, value)),
    )
    result = controller.set_language("fa")
    assert not result.ok and "parakeet" in (result.error or "")
    assert writes == []
    assert not controller.set_stt_model("distil-large-v3", language="fa").ok
    assert writes == []


# ── doctor and `language status` show the combination ───────────────────────

def test_doctor_row_for_the_default_english_install():
    from yazses.system.doctor import _speech_language_checks

    ((name, level, detail),) = _speech_language_checks(Config())
    assert (name, level) == ("Speech language", "OK")
    assert "en — faster-whisper / base.en (English-only) — supported" == detail


def test_doctor_row_for_persian_on_a_multilingual_model():
    from yazses.system.doctor import _speech_language_checks

    ((_, level, detail),) = _speech_language_checks(_cfg(model="small", language="fa"))
    assert level == "OK" and "fa" in detail and "multilingual" in detail


def test_doctor_row_fails_persian_on_parakeet_and_names_what_loads():
    from yazses.system.doctor import _speech_language_checks

    ((_, level, detail),) = _speech_language_checks(
        _cfg(engine="parakeet", model="base.en", language="fa")
    )
    assert level == "FAIL"
    assert "nemo-parakeet-tdt-0.6b-v2" in detail and "NOT SUPPORTED" in detail


def test_doctor_row_warns_on_a_custom_checkpoint():
    from yazses.system.doctor import _speech_language_checks

    ((_, level, _detail),) = _speech_language_checks(_cfg(model="org/custom", language="fa"))
    assert level == "WARN"


def test_language_status_reports_capability(tmp_path):
    import json
    from unittest.mock import MagicMock, patch

    from typer.testing import CliRunner

    from yazses import cli

    path = tmp_path / "config.toml"
    path.write_text('[stt]\nmodel = "base.en"\nlanguage = "fa"\n', encoding="utf-8")
    platform = MagicMock()
    platform.paths.config_file = path
    runner = CliRunner()
    with (
        patch("yazses.cli.get_platform", return_value=platform),
        patch("yazses.stt.download.is_cached", return_value=True),
    ):
        as_json = runner.invoke(cli.app, ["language", "status", "--json"])
        human = runner.invoke(cli.app, ["language", "status"])
    assert as_json.exit_code == 1
    payload = json.loads(as_json.stdout)
    assert payload["multilingual"] is False
    assert payload["language_support"] == "unsupported"
    assert payload["support_source"].startswith("https://")
    assert "Multilingual:  no (English-only)" in human.output
    assert "NOT SUPPORTED" in human.output


def test_config_problem_stays_positionally_compatible():
    problem = ConfigProblem("stt", "model", "x", False)
    assert problem.refused is False
