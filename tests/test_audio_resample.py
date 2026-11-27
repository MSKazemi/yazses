"""The pure resampler behind capture on a device that refuses 16 kHz."""
from __future__ import annotations

from math import ceil

import numpy as np
import pytest

from yazses.audio.resample import StreamResampler, resample

OUT = 16000
RATES = (8000, 22050, 32000, 44100, 48000, 96000)
#: Output samples at each end that the filter computes partly from the silence around a clip.
EDGE = 200


def _tone(freq: float, rate: int, seconds: float = 0.5) -> np.ndarray:
    t = np.arange(int(rate * seconds)) / rate
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


@pytest.mark.parametrize("rate", RATES)
@pytest.mark.parametrize("n", (1, 7, 1000, 4411))
def test_the_output_length_is_the_input_duration_at_the_new_rate(rate, n):
    out = resample(np.zeros(n, dtype=np.float32), rate, OUT)
    assert out.size == ceil(n * OUT / rate)
    assert out.dtype == np.float32


@pytest.mark.parametrize("rate", RATES)
def test_a_speech_band_tone_arrives_unchanged_and_not_delayed(rate):
    out = resample(_tone(1000, rate), rate, OUT)
    expected = _tone(1000, OUT)
    assert out.size == expected.size
    np.testing.assert_allclose(out[EDGE:-EDGE], expected[EDGE:-EDGE], atol=2e-3)


@pytest.mark.parametrize("rate", (44100, 48000))
def test_the_upper_speech_band_is_kept(rate):
    out = resample(_tone(6000, rate), rate, OUT)
    assert _rms(out[EDGE:-EDGE]) == pytest.approx(0.5 / np.sqrt(2), rel=0.01)


@pytest.mark.parametrize("rate, freq", [(48000, 9000), (48000, 12000), (44100, 15000),
                                        (96000, 30000), (22050, 10000)])
def test_content_above_the_new_nyquist_is_removed_not_folded_back(rate, freq):
    """Plain interpolation would alias these into the speech band at nearly full level."""
    out = resample(_tone(freq, rate), rate, OUT)
    assert _rms(out[EDGE:-EDGE]) < 1e-3


def test_a_constant_level_keeps_its_level():
    """The silence gate reads the mean level, so conversion must not scale it."""
    out = resample(np.full(48000, 0.25, dtype=np.float32), 48000, OUT)
    np.testing.assert_allclose(out[EDGE:-EDGE], 0.25, atol=1e-5)


@pytest.mark.parametrize("rate", RATES)
def test_the_output_does_not_depend_on_how_the_input_is_cut(rate):
    rng = np.random.default_rng(7)
    audio = rng.uniform(-0.5, 0.5, 12000).astype(np.float32)
    whole = resample(audio, rate, OUT)
    converter = StreamResampler(rate, OUT)
    parts, at = [], 0
    for size in [0, 1, 1, 3] + [int(s) for s in rng.integers(0, 900, 100)]:
        parts.append(converter.process(audio[at : at + size]))
        at += size
    parts.append(converter.process(audio[at:]))
    parts.append(converter.flush())
    np.testing.assert_allclose(np.concatenate(parts), whole, atol=1e-6)


def test_a_clip_longer_than_one_internal_block_is_converted_whole():
    audio = _tone(440, 48000, seconds=2.0)
    out = resample(audio, 48000, OUT)
    np.testing.assert_allclose(out[EDGE:-EDGE], _tone(440, OUT, 2.0)[EDGE:-EDGE], atol=2e-3)


def test_flush_starts_a_new_signal():
    converter = StreamResampler(44100, OUT)
    audio = _tone(500, 44100, 0.1)
    first = np.concatenate((converter.process(audio), converter.flush()))
    second = np.concatenate((converter.process(audio), converter.flush()))
    np.testing.assert_allclose(first, second, atol=1e-6)
    assert converter.flush().size == 0


def test_a_column_shaped_block_is_read_as_mono():
    converter = StreamResampler(48000, OUT)
    out = np.concatenate((converter.process(np.zeros((480, 1), np.float32)), converter.flush()))
    assert out.shape == (160,)


def test_equal_rates_pass_the_audio_through():
    audio = _tone(1000, OUT)
    np.testing.assert_array_equal(resample(audio, OUT, OUT), audio)


@pytest.mark.parametrize("rates", [(0, OUT), (OUT, 0), (-1, OUT)])
def test_a_nonsense_rate_is_refused(rates):
    with pytest.raises(ValueError):
        StreamResampler(*rates)
