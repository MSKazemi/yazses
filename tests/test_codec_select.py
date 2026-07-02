"""Streaming-codec STT engine selection (ADR-v2-022) — pure select_engine."""
from __future__ import annotations

from dataclasses import dataclass

from yazses.codec.select import select_engine


@dataclass
class _Cfg:
    enabled: bool = False
    backend: str = "kyutai"
    max_delay_ms: int = 500


def test_disabled_uses_whisper():
    assert select_engine(_Cfg(enabled=False)) == "whisper"


def test_enabled_with_backend_uses_codec():
    assert select_engine(_Cfg(enabled=True, backend="kyutai")) == "codec"


def test_enabled_backend_none_falls_back_to_whisper():
    assert select_engine(_Cfg(enabled=True, backend="none")) == "whisper"
    assert select_engine(_Cfg(enabled=True, backend="")) == "whisper"


def test_feature_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    assert "codec" in [f.slug for f in feature_status(Config())]
    assert Config().codec.enabled is False
    # default config never routes to codec
    assert select_engine(Config().codec) == "whisper"
