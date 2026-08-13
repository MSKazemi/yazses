"""The denoise seam finally has an installable backend (#69).

`deepfilternet` cannot supply one — its latest release (0.5.6, 2023-08-31) pins
`numpy>=1.22,<2.0` while this project requires `numpy>=2.4.6`, and those ranges
are disjoint on every Python version. The seam was designed, wired and
permanently unusable. These tests cover the replacement and, more importantly,
the passthrough contract: dictation must never break because a denoiser did.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from yazses.denoise.frontend import apply_denoise


class _Cfg:
    def __init__(self, enabled=True, backend="spectral", strength=1.0):
        self.enabled, self.backend, self.strength = enabled, backend, strength


@pytest.fixture
def fake_noisereduce(monkeypatch):
    """Stand in for the real package: records the call, returns a marker."""
    calls = {}
    module = types.ModuleType("noisereduce")

    def reduce_noise(y, sr, prop_decrease=1.0, stationary=False, **kw):
        calls.update(y=y, sr=sr, prop_decrease=prop_decrease, stationary=stationary)
        return np.zeros_like(y)

    module.reduce_noise = reduce_noise
    monkeypatch.setitem(sys.modules, "noisereduce", module)
    return calls


AUDIO = np.linspace(-0.5, 0.5, 4000, dtype=np.float32)


# ---- the passthrough contract ----------------------------------------------


def test_disabled_is_an_identity_passthrough():
    out = apply_denoise(AUDIO, _Cfg(enabled=False))
    assert out is AUDIO


@pytest.mark.parametrize("backend", ["none", "", None])
def test_backend_none_is_a_passthrough(backend):
    assert apply_denoise(AUDIO, _Cfg(backend=backend)) is AUDIO


def test_a_missing_package_passes_audio_through_rather_than_raising(monkeypatch):
    """The whole point of the seam: a broken denoiser must not break dictation."""
    monkeypatch.setitem(sys.modules, "noisereduce", None)
    out = apply_denoise(AUDIO, _Cfg())
    assert out is AUDIO


def test_a_backend_that_raises_passes_audio_through(monkeypatch):
    module = types.ModuleType("noisereduce")

    def boom(**kw):
        raise RuntimeError("model exploded")

    module.reduce_noise = boom
    monkeypatch.setitem(sys.modules, "noisereduce", module)
    assert apply_denoise(AUDIO, _Cfg()) is AUDIO


def test_deepfilternet_still_passes_through_because_it_cannot_be_installed(monkeypatch):
    """Selecting it is accepted by config and must degrade, not crash."""
    assert apply_denoise(AUDIO, _Cfg(backend="deepfilternet")) is AUDIO


# ---- the spectral backend --------------------------------------------------


def test_spectral_backend_is_invoked_with_the_sample_rate(fake_noisereduce):
    apply_denoise(AUDIO, _Cfg(), sample_rate=16000)
    assert fake_noisereduce["sr"] == 16000


def test_strength_maps_to_prop_decrease(fake_noisereduce):
    apply_denoise(AUDIO, _Cfg(strength=0.4))
    assert fake_noisereduce["prop_decrease"] == pytest.approx(0.4)


def test_strength_is_clamped_into_range(fake_noisereduce):
    apply_denoise(AUDIO, _Cfg(strength=7.0))
    assert fake_noisereduce["prop_decrease"] == 1.0


def test_zero_strength_skips_the_work_entirely(fake_noisereduce):
    out = apply_denoise(AUDIO, _Cfg(strength=0.0))
    assert out is AUDIO
    assert not fake_noisereduce, "must not call the denoiser at all"


def test_non_stationary_estimation_is_used(fake_noisereduce):
    """A room's noise floor drifts; a fixed profile lags it."""
    apply_denoise(AUDIO, _Cfg())
    assert fake_noisereduce["stationary"] is False


def test_dtype_is_preserved(fake_noisereduce):
    """float32 in, float32 out — widening doubles every later copy."""
    out = apply_denoise(AUDIO, _Cfg())
    assert out.dtype == np.float32


def test_a_too_short_buffer_is_returned_unchanged(fake_noisereduce):
    """No noise profile can be estimated from a handful of samples."""
    tiny = np.zeros(64, dtype=np.float32)
    assert apply_denoise(tiny, _Cfg()) is tiny
    assert not fake_noisereduce


# ---- the honesty rule ------------------------------------------------------


def test_the_denoise_extra_exists_and_excludes_deepfilternet():
    """An extra that can never install is worse than an honest 'unavailable'."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    with (root / "pyproject.toml").open("rb") as fh:
        extras = tomllib.load(fh)["project"]["optional-dependencies"]

    assert "denoise" in extras, "the seam now has an installable backend"
    joined = " ".join(extras["denoise"]).lower()
    assert "noisereduce" in joined
    assert "deepfilternet" not in joined, "it pins numpy<2.0; it can never install here"
