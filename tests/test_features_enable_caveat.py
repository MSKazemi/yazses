"""`features enable` warns when a capability is a measured loss on this config.

Enabling streaming on anything but tiny.en is not an error — the config is valid
and the code runs — but it is a silent downgrade: the rolling decode cannot keep
up, so no live text appears before release and the final text lands later than
with streaming off (docs/benchmarks.md, paper/benchmark/bench_streaming.py).
Nothing told the user that, so the advice has to come from `enable_caveat`.
"""
from __future__ import annotations

from yazses.config import Config
from yazses.system.features import enable_caveat, toggleable_slugs


def _cfg(model: str) -> Config:
    cfg = Config()
    cfg.stt.model = model
    return cfg


def test_streaming_on_default_model_warns():
    caveat = enable_caveat("streaming", _cfg("base.en"))
    assert caveat is not None
    assert "tiny.en" in caveat
    assert "base.en" in caveat


def test_streaming_on_larger_model_warns():
    assert enable_caveat("streaming", _cfg("small.en")) is not None


def test_streaming_on_tiny_is_silent():
    """tiny.en is the one configuration the measurement supports."""
    assert enable_caveat("streaming", _cfg("tiny.en")) is None
    assert enable_caveat("streaming", _cfg("tiny")) is None


def test_caveat_is_case_and_whitespace_insensitive():
    assert enable_caveat("  STREAMING ", _cfg("tiny.en")) is None
    assert enable_caveat("streaming", _cfg("  BASE.EN  ")) is not None


def test_unknown_and_unaffected_features_have_no_caveat():
    cfg = _cfg("base.en")
    assert enable_caveat("no-such-feature", cfg) is None
    assert enable_caveat("", cfg) is None
    assert enable_caveat("tray", cfg) is None


def test_caveat_never_raises_for_any_toggleable_feature():
    """It runs on every `features enable`, so it must not be able to break one."""
    cfg = _cfg("base.en")
    for slug in toggleable_slugs():
        enable_caveat(slug, cfg)


def test_caveat_survives_a_config_without_stt():
    class Bare:
        pass

    assert enable_caveat("streaming", Bare()) is None
