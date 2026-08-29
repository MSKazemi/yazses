"""Multilingual dictation: config-to-engine behaviour, at mocked boundaries (#167).

No audio, no model download, no microphone. Recorded speech is personal data and
the licensing on public corpora varies clip by clip, so a fixture nobody may
redistribute is worse than none — see docs/use-cases/multilingual-dictation.md for how to
record your own. What *is* testable offline is the part that silently ruins
non-English dictation: which checkpoint and language reach the engine, and
whether the user is warned when that pairing cannot work.

The failure this pins: an `.en` checkpoint has no language tokens, so pointing it
at German does not raise — Whisper transliterates into fluent-looking English
nonsense. It looks like the software works.
"""

from __future__ import annotations

import logging

import pytest

# The transcription stack cannot be installed on every platform this project runs on:
# `ctranslate2` (via faster-whisper) publishes no FreeBSD wheel and no sdist at all, so
# `pip install -e .` cannot bring it in there. Skipping here rather than keeping a
# hand-maintained ignore list in the CI job means a new decoder test that forgets this
# line fails loudly on that platform instead of silently reducing coverage (#306).
pytest.importorskip("faster_whisper", reason="the decoder stack has no FreeBSD build")

from yazses.config import SttConfig
from yazses.stt.factory import _build_faster_whisper


class _Recorder:
    """Captures what the engine would have been constructed with."""

    def __init__(self):
        self.kwargs = {}


@pytest.fixture
def built(monkeypatch):
    """Build the engine with FasterWhisperEngine replaced by a recorder."""
    rec = _Recorder()

    class _Fake:
        def __init__(self, **kwargs):
            rec.kwargs = kwargs

    import yazses.stt.faster_whisper as fw

    monkeypatch.setattr(fw, "FasterWhisperEngine", _Fake)

    def build(**cfg):
        _build_faster_whisper(SttConfig(**cfg))
        return rec.kwargs

    return build


# ---- what actually reaches the engine --------------------------------------


def test_default_is_english_only():
    """Documented default; the multilingual page is written against it."""
    cfg = SttConfig()
    assert cfg.model == "base.en"
    assert cfg.language == "en"


def test_language_is_threaded_through_to_the_engine(built):
    """`[stt] language` used to be documented but ignored; it must reach decode."""
    assert built(model="small", language="de")["language"] == "de"


def test_multilingual_model_is_passed_verbatim(built):
    assert built(model="medium", language="fa")["model_name"] == "medium"


def test_empty_language_means_autodetect(built):
    """`""` is the documented way to auto-detect per utterance."""
    assert built(model="small", language="")["language"] == ""


# ---- the warning that prevents fluent-looking nonsense ---------------------


@pytest.mark.parametrize("model", ["base.en", "small.en", "tiny.en", "MEDIUM.EN"])
def test_non_english_language_on_an_english_model_warns(built, caplog, model):
    with caplog.at_level(logging.WARNING):
        built(model=model, language="de")
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("English-only" in w for w in warnings), warnings


def test_the_warning_names_the_exact_fix(built, caplog):
    """A warning that does not say what to change is a warning people ignore."""
    with caplog.at_level(logging.WARNING):
        built(model="small.en", language="fa")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "'small'" in text, "must name the multilingual checkpoint to switch to"
    assert "fa" in text, "must name the language that triggered it"


def test_english_on_an_english_model_does_not_warn(built, caplog):
    with caplog.at_level(logging.WARNING):
        built(model="base.en", language="en")
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_non_english_on_a_multilingual_model_does_not_warn(built, caplog):
    """The correct configuration must be silent, or the warning becomes noise."""
    with caplog.at_level(logging.WARNING):
        built(model="small", language="de")
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_autodetect_on_an_english_model_does_not_warn(built, caplog):
    """`language=""` is not a claim about language, so it cannot be contradicted."""
    with caplog.at_level(logging.WARNING):
        built(model="base.en", language="")
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# ---- the documentation must match the code --------------------------------


def test_no_documented_config_pairs_an_english_model_with_another_language():
    """The docs must not show a config the code warns about.

    Walks every TOML example on the multilingual page. A block setting
    `model = "small.en"` beside `language = "de"` would be a documented
    configuration that produces fluent-looking nonsense — exactly the trap the
    page exists to warn people away from.
    """
    import re
    from pathlib import Path

    page = Path(__file__).resolve().parent.parent / "docs/use-cases/multilingual-dictation.md"
    blocks = re.findall(r"```toml\n(.*?)```", page.read_text(encoding="utf-8"), re.S)
    assert blocks, "no toml examples parsed from the multilingual page"

    bad = []
    for block in blocks:
        model = re.search(r'^\s*model\s*=\s*"([^"]+)"', block, re.M)
        language = re.search(r'^\s*language\s*=\s*"([^"]*)"', block, re.M)
        if not model or not language:
            continue
        if model.group(1).lower().endswith(".en") and language.group(1) not in ("en", ""):
            bad.append((model.group(1), language.group(1)))
    assert not bad, f"documented config pairs an English-only model with a language: {bad}"
