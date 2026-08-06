"""The Cocktail Filter gate must stay dormant by default and degrade safely.

`_maybe_cocktail_gate` sits on the dictation hot path between the VAD gate and STT,
and had no direct test. Its per-frame embed closure reads the daemon's embedder, so
these pin both the dormancy conditions and the "never break dictation" guarantee.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from yazses.config import CocktailConfig, Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform


def _daemon(**cocktail) -> Daemon:
    cfg = replace(Config(), cocktail=replace(CocktailConfig(), **cocktail))
    return Daemon(config=cfg, platform=get_platform())


def _audio() -> np.ndarray:
    return np.ones(1600, dtype=np.float32)


def test_dormant_by_default_returns_the_same_array():
    d = _daemon()
    audio = _audio()
    assert d._maybe_cocktail_gate(audio) is audio


def test_enabled_without_an_enrolled_voiceprint_is_a_passthrough():
    """Enabled but un-enrolled must not gate — it would drop all speech."""
    d = _daemon(enabled=True, mode="gate")
    d._embedder = object()          # embedder present...
    d._voiceprint = None            # ...but nothing enrolled
    audio = _audio()
    assert d._maybe_cocktail_gate(audio) is audio


def test_enabled_without_an_embedder_is_a_passthrough():
    d = _daemon(enabled=True, mode="gate")
    d._embedder = None
    d._voiceprint = np.ones(8, dtype=np.float32)
    audio = _audio()
    assert d._maybe_cocktail_gate(audio) is audio


def test_suppress_mode_does_not_use_the_p1_gate():
    """Only `gate` mode is implemented in P1; `suppress` must stay a no-op."""
    d = _daemon(enabled=True, mode="suppress")
    d._embedder = object()
    d._voiceprint = np.ones(8, dtype=np.float32)
    audio = _audio()
    assert d._maybe_cocktail_gate(audio) is audio


def test_a_failing_embedder_falls_back_to_the_original_audio(mocker):
    """An embedder blowing up must never lose the user's dictation."""
    d = _daemon(enabled=True, mode="gate")
    embedder = mocker.MagicMock()
    embedder.embed.side_effect = RuntimeError("model exploded")
    d._embedder = embedder
    d._voiceprint = np.ones(8, dtype=np.float32)

    audio = _audio()
    assert d._maybe_cocktail_gate(audio) is audio


def test_the_gate_runs_and_keeps_matching_frames(mocker):
    """Happy path: a frame matching the target survives the gate."""
    d = _daemon(enabled=True, mode="gate", target_threshold=0.5, window_ms=50)
    target = np.array([1.0, 0.0], dtype=np.float32)
    embedding = mocker.MagicMock()
    embedding.vector = target                      # every frame is the target speaker
    embedder = mocker.MagicMock()
    embedder.embed.return_value = embedding
    d._embedder = embedder
    d._voiceprint = target

    out = d._maybe_cocktail_gate(_audio())

    assert out.size > 0                            # matching speech is not dropped
    assert embedder.embed.called
