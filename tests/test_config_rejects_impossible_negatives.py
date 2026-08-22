"""A negative `vad_threshold` is type-correct, catastrophic, and was reported as valid.

`configcheck` validated **types**. `doctor` reported the result as *"Config validity:
every setting has the expected type"*. So this config loaded with **zero problems**:

    [accessibility]
    vad_threshold = -5.0
    pre_speech_padding_ms = -900

`is_silent` is ``mean(abs(audio)) < vad_threshold``. Against a negative threshold that is
**never true**, so nothing is ever discarded as silence: every burst, including the ones
where nobody spoke, reaches the model — which hallucinates on silence. That is the same
failure the Hallucination Guard exists for and the one `yazses tune` was found feeding
on. And the user asking `doctor` whether their config is good was told it was.

## Why the rule is derived rather than listed

The obvious rule — "no numeric setting may be negative" — is **wrong**, and checking
before writing it is what caught that. Three settings ship negative defaults, because
they are genuinely signed rather than magnitudes:

    [hallucination] logprob_threshold = -1.0     a log probability
    [reask] threshold = -1.0
    [whispermode] tilt_min = -1.0

A hand-maintained list of which settings are magnitudes would be correct the day it was
written and wrong after the next feature. The shipped **default** decides instead: a
setting whose own default is >= 0 is a magnitude and cannot go negative; a signed setting
brings its own permission with it, automatically.
"""

from __future__ import annotations

import dataclasses

import pytest

from yazses.config import Config, load_config_checked
from yazses.configcheck import build_section, negative_is_impossible

#: Settings that are genuinely signed. Asserted below to still be so — if one loses its
#: negative default the rule silently starts rejecting valid values for it.
SIGNED = [
    ("hallucination", "logprob_threshold"),
    ("reask", "threshold"),
    ("whispermode", "tilt_min"),
]


def _field(section: str, key: str):
    node = getattr(Config(), section)
    return {f.name: f for f in dataclasses.fields(node)}[key]


def test_the_catastrophic_case_is_now_repaired(tmp_path) -> None:
    """The defect, at the values that produced it."""
    path = tmp_path / "config.toml"
    path.write_text(
        "[accessibility]\nvad_threshold = -5.0\npre_speech_padding_ms = -900\n"
    , encoding="utf-8")
    loaded = load_config_checked(path)

    assert loaded.config.accessibility.vad_threshold == Config().accessibility.vad_threshold
    assert loaded.config.accessibility.pre_speech_padding_ms >= 0
    reported = " ".join(str(p) for p in loaded.problems)
    assert "vad_threshold" in reported and "negative" in reported, reported
    assert "pre_speech_padding_ms" in reported, reported


def test_a_negative_gate_would_have_discarded_nothing() -> None:
    """Why it matters, stated as code rather than as a claim in a comment."""
    import numpy as np

    from yazses.audio.vad_calibrated import is_silent_calibrated as is_silent

    silence = np.zeros(1600, dtype=np.float32)

    class _Cfg:
        vad_threshold = -5.0

    assert is_silent(silence, _Cfg()) is False, (
        "a negative threshold makes even pure silence 'not silent' — every burst reaches "
        "the model"
    )
    _Cfg.vad_threshold = 0.01
    assert is_silent(silence, _Cfg()) is True


@pytest.mark.parametrize("section,key", SIGNED)
def test_genuinely_signed_settings_still_ship_negative_defaults(section, key) -> None:
    """The premise the whole rule rests on. Checked, because assuming it was wrong."""
    default = _field(section, key).default
    assert isinstance(default, float | int) and default < 0, (
        f"[{section}] {key} no longer defaults negative — the derived rule will now "
        "reject valid values for it"
    )
    assert negative_is_impossible(_field(section, key)) is False


@pytest.mark.parametrize("section,key", SIGNED)
def test_signed_settings_accept_negative_values(section, key, tmp_path) -> None:
    node = getattr(Config(), section)
    cls = type(node)
    problems: list = []
    built = build_section(cls, {key: -2.5}, section, problems)
    assert getattr(built, key) == -2.5
    assert not problems, [str(p) for p in problems]


def test_a_magnitude_is_recognised_as_one() -> None:
    assert negative_is_impossible(_field("accessibility", "vad_threshold")) is True
    assert negative_is_impossible(_field("accessibility", "pre_speech_padding_ms")) is True
    assert negative_is_impossible(_field("hotkey", "hold_threshold_ms")) is True


def test_booleans_and_text_are_untouched() -> None:
    """The rule is about magnitudes; `bool` is an int subclass and must not be caught."""
    assert negative_is_impossible(_field("stt", "model")) is False
    assert negative_is_impossible(_field("general", "update_check")) is False


def test_a_valid_config_still_reports_nothing() -> None:
    """A guard that fires on good input is worse than the bug it fixes."""
    problems: list = []
    build_section(
        type(Config().accessibility),
        {"vad_threshold": 0.02, "pre_speech_padding_ms": 300},
        "accessibility",
        problems,
    )
    assert not problems, [str(p) for p in problems]
