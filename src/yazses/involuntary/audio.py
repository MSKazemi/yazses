"""Audio-side Involuntary-Vocalization Excision (ADR-v2-102) -- pure numpy, no model.

``excise.is_involuntary_vocalization`` classifies one segment from five features. This module
supplies the missing half: it cuts a hold-to-talk burst into isolated sound *islands*, measures
those five features for each, asks the classifier, and silences the islands it flags so a cough
never reaches Whisper (which turns it into "Thank you." or a stray word).

The whole design is biased toward **not** deleting. A detector that removes real speech is worse
than none (AGENTS.md rule 9), so an island is a candidate only if *all* of these hold, and the
burst is returned untouched (the very same array) whenever any one of the burst-level checks fails:

* it is separated from everything else by at least ``GAP_MS`` of quiet. A cough glued to a word
  merges into that word's island, which is voiced, so it is kept;
* it is between ``MIN_ISLAND_MS`` and ``MAX_ISLAND_MS`` long -- a 30 ms plosive release or a 2 s
  sentence is never a candidate;
* it carries no pitch: no more than ``VOICED_FRACTION`` of its frames may show a periodic
  autocorrelation peak. Vowels do, so any word with a vowel is voiced and kept;
* the classifier itself (duration / energy / centroid / voicing / burst) names a kind;
* after the cut the burst still holds at least ``MIN_VOICED_MS`` of voiced speech. A burst that is
  *only* a cough, or only a whisper (no pitch at all), is left alone -- the Hallucination Guard
  and the sotto-voce channel own those cases, and silencing the whole burst here would be a
  deletion with nothing left to prove it was right;
* the flagged islands are at most ``MAX_CUT_FRACTION`` of the burst's active audio. If a third of
  what was said looks like a cough, the detector is wrong, not the speaker.

Silenced spans are zeroed rather than removed, so the burst keeps its length and the word timings
that the prosody / echo / scrub features compute from it. Local audio only; nothing is stored.
"""
from __future__ import annotations

import numpy as np

from yazses.involuntary.excise import is_involuntary_vocalization

FRAME_MS = 20
HOP_MS = 10
#: Quiet needed on both sides before a sound counts as an island of its own. Longer than a stop
#: closure or an ordinary between-word pause, so a plosive release never splits off a word.
GAP_MS = 150
MIN_ISLAND_MS = 80
MAX_ISLAND_MS = 800
#: Share of an island's frames that may look pitched before the island is called voiced.
VOICED_FRACTION = 0.15
#: Normalised autocorrelation peak (pitch range) above which a frame counts as voiced.
VOICING_THRESHOLD = 0.5
#: Speech that must remain in the burst for any cut to be made.
MIN_VOICED_MS = 200
MAX_CUT_FRACTION = 0.34
#: A cough/sneeze starts abruptly: its peak is reached this fast and stands this far over the
#: quiet just before it.
BURST_RISE_MS = 60
BURST_RISE_RATIO = 6.0
#: Margin silenced either side of a flagged island (inside the >= GAP_MS quiet around it).
CUT_PAD_MS = 20
#: Active-frame threshold: this many times the noise floor, and this share of the loudest frame.
FLOOR_MULT = 3.0
PEAK_SHARE = 0.05
PITCH_HZ = (60.0, 400.0)


def _frame_rms(x: np.ndarray, frame: int, hop: int) -> np.ndarray:
    n = 1 + max(0, x.size - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    return np.sqrt(np.mean(x[idx] ** 2, axis=1))


def _frame_voiced(x: np.ndarray, sr: int, frame: int, hop: int) -> np.ndarray:
    """Per-frame: does a normalised autocorrelation peak sit in the pitch range? (32 ms window)"""
    win = max(frame, int(sr * 0.032))
    n = 1 + max(0, x.size - win) // hop
    lo = max(2, int(sr / PITCH_HZ[1]))
    hi = min(win - 1, int(sr / PITCH_HZ[0]))
    out = np.zeros(n, dtype=bool)
    if hi <= lo:
        return out
    for i in range(n):
        seg = x[i * hop:i * hop + win]
        if seg.size < win:
            break
        seg = seg - seg.mean()
        spec = np.fft.rfft(seg, 2 * win)
        ac = np.fft.irfft(spec * np.conj(spec))[:win]
        if ac[0] <= 1e-12:
            continue
        out[i] = float(np.max(ac[lo:hi + 1]) / ac[0]) >= VOICING_THRESHOLD
    return out


def _centroid_hz(seg: np.ndarray, sr: int) -> float:
    spec = np.abs(np.fft.rfft(seg * np.hanning(seg.size))) ** 2
    total = float(spec.sum())
    if total <= 0.0:
        return 0.0
    return float((np.fft.rfftfreq(seg.size, 1.0 / sr) * spec).sum() / total)


def _islands(active: np.ndarray, gap_frames: int) -> list[list[int]]:
    """``[first, last]`` frame runs of ``active``, merging runs closer than ``gap_frames``."""
    runs: list[list[int]] = []
    for i in np.flatnonzero(active):
        if runs and i - runs[-1][1] <= gap_frames:
            runs[-1][1] = int(i)
        else:
            runs.append([int(i), int(i)])
    return runs


def find_involuntary_spans(audio, sample_rate: int) -> list[tuple[float, float, str]]:
    """Flag involuntary non-speech islands in one burst -> ``[(start_s, end_s, kind), ...]``.

    Returns ``[]`` unless every guard in the module docstring passes. Pure and deterministic.
    """
    x = np.asarray(audio, dtype=np.float64).ravel()
    frame = int(sample_rate * FRAME_MS / 1000)
    hop = int(sample_rate * HOP_MS / 1000)
    if x.size < frame * 4 or not np.all(np.isfinite(x)):
        return []
    rms = _frame_rms(x, frame, hop)
    peak = float(rms.max())
    if peak <= 1e-6:
        return []
    floor = max(float(np.percentile(rms, 10)), 1e-6)
    active = rms > max(floor * FLOOR_MULT, peak * PEAK_SHARE)
    islands = _islands(active, GAP_MS // HOP_MS)
    if not islands:
        return []

    voiced = _frame_voiced(x, sample_rate, frame, hop)
    voiced = np.concatenate([voiced, np.zeros(max(0, rms.size - voiced.size), dtype=bool)])

    flagged: list[tuple[int, int, str]] = []
    for first, last in islands:
        dur_ms = (last - first + 1) * HOP_MS + (FRAME_MS - HOP_MS)
        if not (MIN_ISLAND_MS <= dur_ms <= MAX_ISLAND_MS):
            continue
        seg_rms = rms[first:last + 1]
        frac = float(voiced[first:last + 1].mean())
        pre = rms[max(0, first - 8):first]
        pre_level = max(float(np.median(pre)) if pre.size else floor, floor, 1e-6)
        rise_frames = int(np.argmax(seg_rms))
        start_sample = first * hop
        end_sample = min(x.size, last * hop + frame)
        feats = {
            "duration_ms": dur_ms,
            "peak_energy": float(seg_rms.max() / peak),
            "centroid_hz": _centroid_hz(x[start_sample:end_sample], sample_rate),
            "voiced": frac > VOICED_FRACTION,
            "burst": rise_frames * HOP_MS <= BURST_RISE_MS
            and float(seg_rms.max()) >= BURST_RISE_RATIO * pre_level,
        }
        kind = is_involuntary_vocalization(feats)
        if kind is not None:
            flagged.append((start_sample, end_sample, kind))

    if not flagged:
        return []
    cut: set[int] = set()
    for s, e, _ in flagged:
        cut.update(range(s // hop, min(rms.size, e // hop + 1)))
    keep = [int(i) for i in np.flatnonzero(active) if int(i) not in cut]
    if int(voiced[keep].sum()) * HOP_MS < MIN_VOICED_MS:
        return []
    if len(cut) > MAX_CUT_FRACTION * int(active.sum()):
        return []
    return [(s / sample_rate, e / sample_rate, k) for s, e, k in flagged]


def excise_involuntary_audio(audio, sample_rate: int):
    """Silence the flagged islands of ``audio`` -> ``(audio, spans)``.

    ``spans`` is ``[(start_s, end_s, kind), ...]``. With nothing flagged the *input object itself*
    is returned, so the default path stays byte-identical. Otherwise a copy of the same length and
    dtype with the spans (plus ``CUT_PAD_MS`` either side) zeroed.
    """
    spans = find_involuntary_spans(audio, sample_rate)
    if not spans:
        return audio, []
    out = np.array(audio, copy=True)
    pad = int(sample_rate * CUT_PAD_MS / 1000)
    for start_s, end_s, _ in spans:
        a = max(0, int(start_s * sample_rate) - pad)
        b = min(out.shape[0], int(end_s * sample_rate) + pad)
        out[a:b] = 0
    return out, spans
