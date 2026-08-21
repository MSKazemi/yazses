"""The settings window can now change the three settings that decide what YazSes hears.

Before this, the window exposed 147 feature toggles and exactly three value
settings — hotkey, microphone, silence threshold. The model, the spoken language
and the injection backend were editable only by hand-editing TOML, despite being
the settings that most change what the product does.

The interesting part is not the widgets, it is the **refusal**. Choosing an
English-only checkpoint while `[stt] language` names another language does not
fail at runtime: Whisper transliterates, so the user gets fluent-looking English
nonsense and no error anywhere. The daemon logs a warning, but a log line loses to
a window that will not save the pair in the first place.

That rule now has one implementation (`stt/download.py::language_model_problem`),
used by both the daemon's startup path and this window. It began as an inline
condition inside `stt/factory.py`, where the settings window could not reach it —
and a second copy is how the two would drift.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from yazses.settingsui.controller import SettingsController
from yazses.settingsui.controls import (
    INJECTION_BACKENDS,
    LANGUAGE_CHOICES,
    language_choices,
    model_choices,
)
from yazses.stt.download import WHISPER_MODELS, is_english_only, language_model_problem


# ---- the shared rule ------------------------------------------------------
def test_an_en_checkpoint_is_recognised_as_english_only():
    assert is_english_only("base.en")
    assert is_english_only("  SMALL.EN  ")
    assert not is_english_only("small")
    assert not is_english_only("large-v3")


@pytest.mark.parametrize("language", ["", "en", "EN"])
def test_english_or_auto_is_never_a_problem(language):
    assert language_model_problem("base.en", language) is None


def test_a_non_english_language_on_an_en_model_is_refused_with_the_fix():
    problem = language_model_problem("base.en", "fa")
    assert problem is not None
    assert "English-only" in problem
    assert "'base'" in problem, f"must name the model to switch to: {problem}"


def test_a_multilingual_model_takes_any_language():
    assert language_model_problem("large-v3", "fa") is None


# ---- the dropdowns --------------------------------------------------------
def test_the_model_list_comes_from_the_shipped_registry():
    """Not a hand-copied list, or the window and `yazses models` drift apart."""
    names = model_choices(WHISPER_MODELS)
    assert "base.en" in names and "large-v3" in names
    assert names == sorted(names), "sorted so the .en/multilingual pairs sit together"


def test_a_hand_edited_model_is_kept_rather_than_replaced():
    """A hub id or path is a real model; silently switching it would be data loss."""
    names = model_choices(WHISPER_MODELS, current="my-org/my-finetune")
    assert names[0] == "my-org/my-finetune"


def test_a_configured_language_outside_the_list_survives():
    rows = language_choices(current="cy")
    assert any(value == "cy" for _, value in rows)


def test_auto_detect_is_offered_as_a_real_choice():
    assert ("Auto-detect (per utterance)", "") == LANGUAGE_CHOICES[0]


# ---- the controller -------------------------------------------------------
@dataclass
class _Stt:
    model: str = "base.en"
    language: str = ""


@dataclass
class _Injection:
    backend: str = "auto"


@dataclass
class _Cfg:
    stt: _Stt = field(default_factory=_Stt)
    injection: _Injection = field(default_factory=_Injection)


def _controller(cfg: _Cfg, writes: list):
    return SettingsController(
        load_config=lambda: cfg,
        writer=lambda section, key, value, quote: writes.append((section, key, value)),
    )


def test_setting_a_model_writes_it():
    writes: list = []
    result = _controller(_Cfg(), writes).set_stt_model("large-v3")
    assert result.ok, result.error
    assert ("stt", "model", "large-v3") in writes


def test_choosing_an_en_model_is_refused_when_the_language_is_not_english():
    """The whole point: refused *before* writing, not logged after."""
    writes: list = []
    cfg = _Cfg(stt=_Stt(model="large-v3", language="fa"))
    result = _controller(cfg, writes).set_stt_model("base.en")
    assert not result.ok
    assert "English-only" in (result.error or "")
    assert writes == [], "nothing may be written when the pair is refused"


def test_choosing_a_language_is_refused_when_the_model_cannot_decode_it():
    writes: list = []
    cfg = _Cfg(stt=_Stt(model="base.en", language="en"))
    result = _controller(cfg, writes).set_language("de")
    assert not result.ok
    assert writes == []


def test_auto_detect_is_writable_and_is_not_treated_as_empty():
    writes: list = []
    cfg = _Cfg(stt=_Stt(model="base.en", language="en"))
    result = _controller(cfg, writes).set_language("")
    assert result.ok, result.error
    assert ("stt", "language", "") in writes


def test_an_empty_model_is_refused_rather_than_defaulted():
    writes: list = []
    result = _controller(_Cfg(), writes).set_stt_model("   ")
    assert not result.ok
    assert writes == []


@pytest.mark.parametrize("backend", INJECTION_BACKENDS)
def test_every_offered_injection_backend_is_accepted(backend):
    """Guards the guard: a list the setter rejects would be an unusable dropdown."""
    writes: list = []
    result = _controller(_Cfg(), writes).set_injection_backend(backend)
    assert result.ok, result.error
    assert ("injection", "backend", backend) in writes


def test_an_unknown_injection_backend_is_refused_and_names_the_options():
    writes: list = []
    result = _controller(_Cfg(), writes).set_injection_backend("telepathy")
    assert not result.ok
    assert "auto" in (result.error or ""), "the error must list what is valid"
    assert writes == []


def test_a_write_failure_is_reported_rather_than_raised():
    """Qt must never see an exception from a setter."""

    def _boom(*_args):
        raise OSError("read-only config")

    controller = SettingsController(load_config=lambda: _Cfg(), writer=_boom)
    result = controller.set_stt_model("small")
    assert not result.ok
    assert "read-only config" in (result.error or "")
