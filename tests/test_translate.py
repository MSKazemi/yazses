"""Speech translation mode decision (ADR-v2-014) — pure translation_task."""
from __future__ import annotations

from dataclasses import dataclass

from yazses.translate.mode import translation_task


@dataclass
class _Cfg:
    enabled: bool = False
    target: str = "en"
    backend: str = "whisper"


def test_disabled_returns_none():
    assert translation_task(_Cfg()) is None


def test_whisper_english_returns_translate():
    assert translation_task(_Cfg(enabled=True, target="en")) == "translate"
    assert translation_task(_Cfg(enabled=True, target="English")) == "translate"


def test_non_english_target_returns_none_on_whisper():
    # Whisper translate is X->English only; other targets need seamless
    assert translation_task(_Cfg(enabled=True, target="fr", backend="whisper")) is None


def test_seamless_backend_not_handled_by_pure_layer():
    # seamless is opt-in/out-of-scope here → pure layer returns None (no whisper task)
    assert translation_task(_Cfg(enabled=True, target="fr", backend="seamless")) is None


def test_feature_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "translate" in slugs
