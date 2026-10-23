"""Level stream -> Morse pulses and gaps (pure) — the producer for ADR-v2-105.

`decode.py` classifies *durations*; nothing upstream measured them. This module turns a
``(timestamp_ms, level)`` stream into pulse and gap durations and feeds them to
:class:`~yazses.morsevox.decode.MorseDecoder`. The level is whatever scalar the caller
already has — the daemon computes ``mean(|samples|)`` per audio chunk for the overlay
and the VAD gate — so this module needs no audio, no numpy and no model.

Two layers keep a noisy level from becoming a stream of spurious symbols:

* **Hysteresis.** A pulse starts when the level reaches ``on_level`` and continues until
  it falls below ``off_level`` (``off_level <= on_level``). A level hovering near one
  threshold therefore does not toggle on every sample.
* **Debounce.** A drop below ``off_level`` shorter than ``bridge_ms`` inside a pulse is
  bridged, so a wavering hum stays one dash. A pulse with less than ``min_pulse_ms`` of
  voiced time is discarded as a click and the silence around it is treated as unbroken.

:class:`MorseStream` composes the segmenter with the decoder. It emits a letter as soon
as the silence after it reaches ``letter_gap_ms`` rather than waiting for the next
pulse, and (optionally) re-fits the dot/dash threshold to the user's own rhythm with
:func:`~yazses.morsevox.decode.adapt_dot_threshold`.

Everything here is deterministic, pure state; time comes only from the caller. At
runtime it is constructed by :class:`~yazses.morsevox.mode.MorseMode` once Morse mode is
entered, fed by the level stream in `morsevox/runtime.py`.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, replace

from yazses.morsevox.decode import (
    MorseCalib,
    MorseDecoder,
    adapt_dot_threshold,
    classify_gap,
    classify_pulse,
)


@dataclass(frozen=True)
class SegmenterConfig:
    """Thresholds for turning a level into on/off, and the debounce windows (ms).

    ``on_level``/``off_level`` are in the caller's level units. There is deliberately no
    default for ``on_level``: an absolute loudness that suits one microphone sits below
    another room's noise floor, so the caller must supply a measured value (the daemon's
    ``accessibility.vad_threshold`` is the obvious source). :meth:`from_threshold`
    derives ``off_level`` from it.
    """

    on_level: float
    off_level: float
    min_pulse_ms: float = 40.0
    bridge_ms: float = 60.0

    def __post_init__(self) -> None:
        for name in ("on_level", "off_level", "min_pulse_ms", "bridge_ms"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite number >= 0, got {value!r}")
        if self.off_level > self.on_level:
            raise ValueError(
                f"off_level ({self.off_level}) must not exceed on_level ({self.on_level})"
            )

    @classmethod
    def from_threshold(cls, threshold: float, *, hysteresis: float = 0.6,
                       min_pulse_ms: float = 40.0, bridge_ms: float = 60.0) -> SegmenterConfig:
        """``on_level = threshold``, ``off_level = threshold * hysteresis`` (0 < h <= 1)."""
        if not 0.0 < hysteresis <= 1.0:
            raise ValueError(f"hysteresis must be in (0, 1], got {hysteresis!r}")
        return cls(on_level=threshold, off_level=threshold * hysteresis,
                   min_pulse_ms=min_pulse_ms, bridge_ms=bridge_ms)


@dataclass(frozen=True)
class Segment:
    """One accepted pulse or one completed gap between two accepted pulses."""

    kind: str          # "pulse" | "gap"
    start_ms: float
    duration_ms: float


class PulseSegmenter:
    """Hysteresis + debounce segmenter over a ``(t_ms, level)`` stream. Pure state.

    A rising edge opens a *candidate* pulse. Drops below ``off_level`` shorter than
    ``bridge_ms`` are bridged; a drop that lasts ``bridge_ms`` closes the candidate at the
    moment the level fell. The candidate becomes a pulse once its *voiced* time (bridged
    dropouts excluded) reaches ``min_pulse_ms``; one that closes before then was a click
    and is discarded, leaving the silence around it unbroken. Counting voiced time rather
    than span is what stops two clicks a few samples apart from bridging into a dot.

    :meth:`push` returns the segments completed by that sample, in time order: the gap
    before a pulse when that pulse is accepted, the pulse itself when it closes. The
    silence before the first pulse is not a gap and is never reported.

    Samples whose timestamp goes backwards are ignored; a non-finite level is treated as
    silence. Neither raises, so a glitching clock or a NaN chunk cannot kill the caller.
    """

    def __init__(self, config: SegmenterConfig) -> None:
        self._cfg = config
        self._last_t: float | None = None
        self._raw_on = False
        # When the current inter-pulse silence began; None before the first pulse and
        # while an accepted pulse is in progress.
        self._silence_start: float | None = None
        # The open pulse (candidate or accepted), if any.
        self._pulse_start: float | None = None
        self._accepted = False
        self._voiced_ms = 0.0               # voiced time up to the last falling edge
        self._rise_at: float | None = None  # last rising edge, while raw-on
        self._off_at: float | None = None   # last falling edge, while raw-off in a pulse

    @property
    def config(self) -> SegmenterConfig:
        return self._cfg

    @property
    def in_pulse(self) -> bool:
        """True while an accepted pulse is open (including a dropout being bridged)."""
        return self._pulse_start is not None and self._accepted

    def silence_ms(self, t_ms: float) -> float | None:
        """How long the current inter-pulse silence has lasted at ``t_ms``, or None.

        None before the first accepted pulse and while an accepted pulse is open. While a
        candidate pulse is still being judged the value is frozen at its rising edge, so a
        pulse about to be accepted cannot push the preceding gap past a boundary it never
        reached.
        """
        if self._silence_start is None:
            return None
        end = self._pulse_start if self._pulse_start is not None else t_ms
        return max(0.0, end - self._silence_start)

    def push(self, t_ms: float, level: float) -> list[Segment]:
        """Feed one sample; return the segments it completed."""
        if not math.isfinite(t_ms) or (self._last_t is not None and t_ms < self._last_t):
            return []
        self._last_t = t_ms
        if not math.isfinite(level):
            level = 0.0

        out: list[Segment] = []
        # Timers that elapsed before this sample are judged on the previous raw state.
        self._resolve(t_ms, out)

        cfg = self._cfg
        raw_on = level >= cfg.off_level if self._raw_on else level >= cfg.on_level
        if raw_on and not self._raw_on:
            if self._pulse_start is None:
                self._pulse_start = t_ms
                self._accepted = False
                self._voiced_ms = 0.0
            self._off_at = None            # inside a pulse: the dropout is bridged
            self._rise_at = t_ms
        elif not raw_on and self._raw_on:
            if self._rise_at is not None:
                self._voiced_ms += t_ms - self._rise_at
            self._rise_at = None
            self._off_at = t_ms
        self._raw_on = raw_on
        self._resolve(t_ms, out)
        return out

    def flush(self, t_ms: float) -> list[Segment]:
        """End of stream: close an open pulse at its falling edge (or at ``t_ms``)."""
        out: list[Segment] = []
        if self._pulse_start is not None:
            if self._last_t is not None and (not math.isfinite(t_ms) or t_ms < self._last_t):
                t_ms = self._last_t
            if self._rise_at is not None:
                self._voiced_ms += t_ms - self._rise_at
                self._rise_at = None
            self._close(self._off_at if self._off_at is not None else t_ms, out)
        self._raw_on = False
        return out

    # ---- internals ---------------------------------------------------------

    def _voiced(self, t_ms: float) -> float:
        extra = t_ms - self._rise_at if self._rise_at is not None else 0.0
        return self._voiced_ms + extra

    def _resolve(self, t_ms: float, out: list[Segment]) -> None:
        if self._pulse_start is None:
            return
        if not self._accepted and self._voiced(t_ms) >= self._cfg.min_pulse_ms:
            self._accept(out)
        if self._off_at is not None and t_ms - self._off_at >= self._cfg.bridge_ms:
            self._close(self._off_at, out)

    def _accept(self, out: list[Segment]) -> None:
        start = self._pulse_start
        assert start is not None
        if self._silence_start is not None:
            out.append(Segment("gap", self._silence_start, start - self._silence_start))
        self._silence_start = None
        self._accepted = True

    def _close(self, end_ms: float, out: list[Segment]) -> None:
        start = self._pulse_start
        assert start is not None
        if not self._accepted and self._voiced_ms >= self._cfg.min_pulse_ms:
            self._accept(out)
        if self._accepted:
            out.append(Segment("pulse", start, max(0.0, end_ms - start)))
            self._silence_start = end_ms
        # else: a click — the silence (if any) carries on from where it began.
        self._pulse_start = None
        self._accepted = False
        self._voiced_ms = 0.0
        self._rise_at = None
        self._off_at = None


class MorseStream:
    """Level stream -> decoded text: :class:`PulseSegmenter` feeding :class:`MorseDecoder`.

    :meth:`push` returns the text completed by that sample (usually ``""``). A letter is
    emitted once the silence after it reaches ``calib.letter_gap_ms`` and a space once it
    reaches ``calib.word_gap_ms`` — each at most once per silence, whether the boundary is
    seen live (:meth:`PulseSegmenter.silence_ms`) or only when the next pulse closes the gap.
    A letter whose code is not in the Morse table is dropped, as ``MorseDecoder`` does.

    A prosign (SK, see `decode.py`) types nothing and no space after it. The sample that
    completes it stops there: any segment after it in that same sample is not decoded, and
    :meth:`take_prosign` reports it once, so the caller can end the mode.

    With ``adapt=True`` the dot/dash threshold is re-fitted after each pulse from the last
    ``window`` pulse durations — but only once ``min_samples`` are in hand and the long half
    averages at least ``min_ratio`` times the short half. That guard matters: a run of
    nothing but dots (``"eeee"`` or ``"5"``) has no dash cluster, and splitting it at its
    median would drag the threshold into the dots themselves.
    """

    def __init__(self, segmenter: PulseSegmenter, calib: MorseCalib | None = None, *,
                 adapt: bool = False, alpha: float = 0.3, window: int = 16,
                 min_samples: int = 6, min_ratio: float = 2.0) -> None:
        if not 2 <= min_samples <= window:
            raise ValueError(f"need 2 <= min_samples <= window, got {min_samples}, {window}")
        self._seg = segmenter
        self._calib = calib if calib is not None else MorseCalib()
        self._decoder = MorseDecoder()
        self._adapt = adapt
        self._alpha = alpha
        self._min_samples = min_samples
        self._min_ratio = min_ratio
        self._durations: deque[float] = deque(maxlen=window)
        self._letter_sent = False
        self._word_sent = False
        self._prosign: str | None = None      # reported once by take_prosign()
        self._closed_prosign = False          # a prosign closed during this push/flush

    @property
    def calib(self) -> MorseCalib:
        """The current timing thresholds (changes over time when ``adapt`` is on)."""
        return self._calib

    def take_prosign(self) -> str | None:
        """The prosign (``"SK"``) decoded since the last call, once; else None."""
        prosign, self._prosign = self._prosign, None
        return prosign

    def push(self, t_ms: float, level: float) -> str:
        """Feed one level sample; return any text it completed (up to a prosign)."""
        text = []
        self._closed_prosign = False
        for seg in self._seg.push(t_ms, level):
            text.append(self._on_segment(seg))
            if self._closed_prosign:
                return "".join(text)
        silence = self._seg.silence_ms(t_ms)
        if silence is not None:
            text.append(self._on_silence(silence))
        return "".join(text)

    def flush(self, t_ms: float) -> str:
        """End of stream: close any pulse and emit the pending letter (no trailing space)."""
        self._closed_prosign = False
        text = [self._on_segment(seg) for seg in self._seg.flush(t_ms)]
        after_prosign = self._closed_prosign
        if not self._letter_sent:
            tail = self._feed("gap_letter")         # empty buffer -> ""
            if not after_prosign:                   # nothing keyed after SK is typed
                text.append(tail)
        self._letter_sent = self._word_sent = False
        return "".join(text)

    # ---- internals ---------------------------------------------------------

    def _feed(self, token: str) -> str:
        out = self._decoder.feed(token) or ""
        prosign = self._decoder.take_prosign()
        if prosign is not None:
            self._prosign = prosign
            self._closed_prosign = True
        return out

    def _on_segment(self, seg: Segment) -> str:
        if seg.kind == "gap":
            out = self._on_silence(seg.duration_ms)
            self._letter_sent = self._word_sent = False
            return out
        token = classify_pulse(seg.duration_ms, self._calib)
        self._feed(token)
        self._letter_sent = self._word_sent = False
        if self._adapt:
            self._durations.append(seg.duration_ms)
            self._maybe_refit()
        return ""

    def _on_silence(self, silence_ms: float) -> str:
        kind = classify_gap(silence_ms, self._calib)
        out = ""
        if kind in ("gap_letter", "gap_word") and not self._letter_sent:
            out += self._feed("gap_letter")
            self._letter_sent = True
            if self._closed_prosign:
                self._word_sent = True  # a prosign is followed by no space
        if kind == "gap_word" and not self._word_sent:
            # The letter is already out, so the decoder's buffer is empty and gap_word
            # yields just the space.
            out += self._feed("gap_word")
            self._word_sent = True
        return out

    def _maybe_refit(self) -> None:
        if len(self._durations) < self._min_samples:
            return
        vals = sorted(self._durations)
        mid = len(vals) // 2
        short = sum(vals[:mid]) / mid
        long = sum(vals[mid:]) / (len(vals) - mid)
        if short <= 0 or long / short < self._min_ratio:
            return
        refit = adapt_dot_threshold(vals, self._calib, alpha=self._alpha)
        self._calib = replace(self._calib, dot_max_ms=refit.dot_max_ms)
