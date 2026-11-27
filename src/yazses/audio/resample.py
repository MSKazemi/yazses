"""Streaming sample-rate conversion for capture devices that refuse 16 kHz. Pure.

Some inputs only open at their own rate -- a raw ALSA ``hw:`` device, a Windows WASAPI
endpoint -- so the audio is captured there and converted before anything else sees it.
NumPy only: the base install has no resampling library, and this does not add one.

The filter is a Kaiser-windowed sinc evaluated as a polyphase FIR at the exact rational
ratio (44100 -> 16000 is 160/441), so output positions are integer arithmetic and cannot
drift over a long recording. It is a proper low-pass: content above the new Nyquist is
removed instead of folding back into the speech band, which plain interpolation would do.
Output sample ``k`` sits at time ``k / out_rate``, so there is no delay to compensate; the
price is that the last few milliseconds are only produced by :meth:`StreamResampler.flush`.
"""
from __future__ import annotations

from math import ceil, gcd

import numpy as np

#: Sinc zero crossings kept on each side of the filter's centre. More is a sharper cut-off.
_ZERO_CROSSINGS = 32
#: Cut-off as a fraction of the lower of the two Nyquist frequencies. With the length and
#: window below, the transition band ends just under that Nyquist.
_ROLLOFF = 0.92
#: Kaiser window shape: about 80 dB of stop-band attenuation.
_KAISER_BETA = 8.0
#: Output samples computed per pass, which bounds the temporary memory of a long clip.
_BLOCK = 4096


class StreamResampler:
    """Convert mono float32 audio from ``in_rate`` to ``out_rate``, chunk by chunk.

    The output does not depend on how the input is cut into chunks. Not thread-safe.
    """

    def __init__(self, in_rate: int, out_rate: int) -> None:
        if in_rate <= 0 or out_rate <= 0:
            raise ValueError(f"sample rates must be positive, got {in_rate} -> {out_rate}")
        common = gcd(int(in_rate), int(out_rate))
        self._up = int(out_rate) // common
        self._down = int(in_rate) // common
        cutoff = _ROLLOFF * min(1.0, self._up / self._down)  # of the input Nyquist
        self._half = ceil(_ZERO_CROSSINGS / cutoff)
        # taps[p, j] weighs input sample ``i - half + 1 + j`` for the output at ``i + p/up``.
        offsets = np.arange(-self._half + 1, self._half + 1, dtype=np.float64)
        distance = np.arange(self._up, dtype=np.float64)[:, None] / self._up - offsets
        shape = np.sqrt(np.clip(1.0 - (distance / self._half) ** 2, 0.0, 1.0))
        taps = np.sinc(cutoff * distance) * np.i0(_KAISER_BETA * shape)
        taps /= taps.sum(axis=1, keepdims=True)  # unity gain at 0 Hz for every phase
        self._taps = taps.astype(np.float32)
        self.reset()

    def reset(self) -> None:
        """Forget all input: the next chunk starts a new signal."""
        # Silence before the first sample, so the first outputs have a full filter window.
        self._buf = np.zeros(self._half - 1, dtype=np.float32)
        self._buf_start = -(self._half - 1)  # input index of ``_buf[0]``
        self._n_in = 0
        self._n_out = 0

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Return every output sample that ``samples`` completes (possibly none)."""
        chunk = np.asarray(samples, dtype=np.float32).ravel()
        self._buf = np.concatenate((self._buf, chunk))
        self._n_in += chunk.size
        # Output k reads input up to ``floor(k * down / up) + half``.
        limit = (self._n_in - self._half) * self._up
        return self._emit(-(-limit // self._down) if limit > 0 else 0)

    def flush(self) -> np.ndarray:
        """Return the outputs still waiting for input, then :meth:`reset`.

        Over a whole signal ``process`` plus ``flush`` yield ``ceil(n * out / in)``
        samples.
        """
        end = -(-self._n_in * self._up // self._down)
        self._buf = np.concatenate((self._buf, np.zeros(self._half, dtype=np.float32)))
        tail = self._emit(end)
        self.reset()
        return tail

    def _emit(self, end: int) -> np.ndarray:
        """Compute output samples ``_n_out`` up to ``end`` and drop input no longer needed."""
        if end <= self._n_out:
            return np.zeros(0, dtype=np.float32)
        out = np.empty(end - self._n_out, dtype=np.float32)
        columns = np.arange(2 * self._half)
        for begin in range(self._n_out, end, _BLOCK):
            stop = min(begin + _BLOCK, end)
            position = np.arange(begin, stop, dtype=np.int64) * self._down
            first = position // self._up - self._half + 1 - self._buf_start
            window = self._buf[first[:, None] + columns]
            out[begin - self._n_out : stop - self._n_out] = np.einsum(
                "ij,ij->i", window, self._taps[position % self._up]
            )
        self._n_out = end
        drop = end * self._down // self._up - self._half + 1 - self._buf_start
        if drop > 0:
            self._buf = self._buf[drop:]
            self._buf_start += drop
        return out


def resample(audio: np.ndarray, in_rate: int, out_rate: int) -> np.ndarray:
    """Convert a whole mono clip from ``in_rate`` to ``out_rate``."""
    if in_rate == out_rate:
        return np.asarray(audio, dtype=np.float32).ravel()
    converter = StreamResampler(in_rate, out_rate)
    return np.concatenate((converter.process(audio), converter.flush()))
