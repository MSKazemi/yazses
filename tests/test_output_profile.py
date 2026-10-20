"""Language output profile registry (FA-01, #509; design: draft PR #483).

Pure unit tests plus the one factory seam. The Persian transform itself is
covered by ``tests/test_persian_text.py``; here the subject is *which profile a
configuration selects* and that everything else is a byte-identical pass-through.
"""
from __future__ import annotations

import pytest

from yazses.config import SttConfig
from yazses.postprocess.output_profile import (
    PASS_THROUGH,
    PERSIAN,
    PassThroughProfile,
    PersianProfile,
    canonical_language,
    profile_for,
)
from yazses.stt.factory import _with_persian_normaliser


class _Stub:
    name = "stub"

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "كتاب علي"


class _Cfg:
    """Duck-typed `[stt]` section; extra attributes stand in for unrelated settings."""

    def __init__(self, language, persian_normalisation=True, **extra):
        self.language = language
        self.persian_normalisation = persian_normalisation
        for key, value in extra.items():
            setattr(self, key, value)


# -- registry / interface ----------------------------------------------------


@pytest.mark.parametrize("lang", ["fa", "FA", " fa ", "fas", "fa-IR", "persian"])
def test_persian_codes_select_the_persian_profile(lang):
    profile = profile_for(lang)
    assert profile is PERSIAN
    assert isinstance(profile, PersianProfile)
    assert profile.language_code == "fa"


@pytest.mark.parametrize("lang", ["en", "de", "zh", "ar", "ur", "", None, 0, "xx"])
def test_every_other_language_is_pass_through(lang):
    profile = profile_for(lang)
    assert profile is PASS_THROUGH
    assert isinstance(profile, PassThroughProfile)


@pytest.mark.parametrize("lang", ["en", "zh", "ar", "", None])
def test_pass_through_builds_no_normaliser_even_with_every_switch_on(lang):
    cfg = _Cfg(lang, chinese_script="simplified", persian_normalisation=True)
    assert profile_for(lang).build_normaliser(cfg) is None


def test_canonical_language_folds_aliases_and_keeps_others_lowercased():
    assert canonical_language("Persian") == "fa"
    assert canonical_language("EN") == "en"
    assert canonical_language(None) == ""


def test_persian_profile_delegates_to_the_opt_in_gate():
    """Selecting the profile alone changes nothing: `persian_normalisation` still gates it."""
    assert PERSIAN.build_normaliser(_Cfg("fa", persian_normalisation=False)) is None
    normalise = PERSIAN.build_normaliser(_Cfg("fa"))
    assert normalise is not None
    assert normalise("كتاب") == "کتاب"


def test_profile_for_takes_exactly_one_argument_the_stt_language():
    """No UI-locale parameter exists, so a locale cannot select a profile by construction."""
    import inspect

    params = list(inspect.signature(profile_for).parameters)
    assert params == ["language"]


# -- selection is by STT language, not UI locale -----------------------------


@pytest.mark.parametrize("var", ["LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE"])
def test_a_persian_ui_locale_does_not_activate_the_profile(monkeypatch, var):
    for other in ("LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(other, raising=False)
    monkeypatch.setenv(var, "fa_IR.UTF-8")
    engine = _Stub()
    cfg = SttConfig(language="en", persian_normalisation=True)
    assert profile_for(cfg.language) is PASS_THROUGH
    assert _with_persian_normaliser(engine, cfg) is engine


@pytest.mark.parametrize("var", ["LANG", "LC_ALL"])
def test_an_english_ui_locale_does_not_deactivate_it(monkeypatch, var):
    for other in ("LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(other, raising=False)
    monkeypatch.setenv(var, "en_US.UTF-8")
    engine = _Stub()
    wrapped = _with_persian_normaliser(
        engine, SttConfig(language="fa", persian_normalisation=True)
    )
    assert wrapped is not engine
    assert wrapped.transcribe(None) == "کتاب علی"


def test_a_locale_like_attribute_on_the_config_is_ignored():
    cfg = _Cfg("en", locale="fa", ui_language="fa")
    assert profile_for(cfg.language).build_normaliser(cfg) is None


# -- factory seam: default configs stay wrapper-free --------------------------


@pytest.mark.parametrize("lang", ["en", "zh", "de", ""])
def test_factory_leaves_non_persian_engines_untouched(lang):
    engine = _Stub()
    assert _with_persian_normaliser(engine, SttConfig(language=lang)) is engine


def test_factory_leaves_fa_untouched_until_the_user_opts_in():
    engine = _Stub()
    assert _with_persian_normaliser(engine, SttConfig(language="fa")) is engine
