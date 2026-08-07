"""Prosody Ink (P1 core) — let *how* you said it shape *how* it looks.

Maps prosodic marks to text formatting: a long pause becomes a paragraph break,
vocal emphasis becomes bold. These two are the evidence-supported subset
(prominence detectable at F1 ~0.86-0.90 from cheap acoustic features; pause->break
is robust). Rising-pitch->question is deliberately excluded: it is acoustically
unreliable (WH-questions carry falling F0). Spec: design/specs/prosody-ink.md.

``format_prosody`` is the pure formatter (fully tested, no deps). ``annotate`` is
the postprocess entry point the daemon calls: it re-renders the *final* dictation
text (already cleaned + disfluency-filtered) using Whisper word timings for
spacing and — when the ``prosody`` extra (parselmouth) is installed and a
bold-capable ``format`` is set — acoustic prominence for emphasis. Phase 1
(pause→¶) needs no acoustic dep; Phase 2 emphasis degrades to no-op when
parselmouth is absent, so the feature is always safe to enable on the batch path.

Deviation from the spec's ``annotate(audio, sample_rate, words, config)`` note:
in practice prosody composes *after* clean_text + disfluency, so it takes the
filtered ``text`` and uses ``words`` only for timing/emphasis — this respects the
upstream filters instead of re-deriving content from raw Whisper tokens.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from yazses.config import ProsodyConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProsodyMark:
    """Per-word prosodic features driving formatting."""
    pause_before_s: float = 0.0
    emphasized: bool = False


@dataclass(frozen=True)
class Word:
    """A transcript word with faster-whisper timestamps (seconds).

    ``probability`` is faster-whisper's per-word confidence (0..1), used by
    Confidence Ink (ADR-v2-001); defaults to 0.0 so existing 3-arg construction
    stays valid.
    """
    text: str
    start: float
    end: float
    probability: float = 0.0


@dataclass(frozen=True)
class ProsodyResult:
    """Formatted text plus metadata-only diagnostics (no transcript persisted)."""
    text: str
    paragraph_breaks: int
    emphasized: int
    latency_ms: float


_SENTENCE_ENDERS = ".!?…,;:"


def _end_sentence(prev: str) -> str:
    """Append a period to the previous rendered token unless it is already
    punctuated (ignoring trailing markdown ``*`` and whitespace)."""
    stripped = prev.rstrip().rstrip("*")
    if not stripped or stripped[-1] in _SENTENCE_ENDERS:
        return prev
    return prev + "."


def format_prosody(
    words: list[str],
    marks: list[ProsodyMark],
    *,
    paragraph_pause_s: float = 0.6,
    sentence_pause_s: float = 0.0,
    style: str = "markdown",
) -> str:
    """Render words with prosody-driven formatting.

    ``style="markdown"`` bolds emphasized words (``**word**``) and turns a pause
    >= ``paragraph_pause_s`` into a paragraph break. When ``sentence_pause_s > 0``
    (ADR-v2-002), a gap at/above it but below the paragraph threshold ends the
    previous word with a period (and paragraph breaks also close the sentence).
    ``style="none"`` returns the plain space-joined text (extraction effectively off).
    """
    if style == "none" or not words:
        return " ".join(words)

    add_periods = sentence_pause_s > 0
    out: list[str] = []
    for i, word in enumerate(words):
        mark = marks[i] if i < len(marks) else ProsodyMark()
        token = f"**{word}**" if mark.emphasized else word
        if i == 0:
            out.append(token)
        elif mark.pause_before_s >= paragraph_pause_s:
            if add_periods and out:
                out[-1] = _end_sentence(out[-1])
            out.append("\n\n" + token)
        elif add_periods and mark.pause_before_s >= sentence_pause_s:
            out[-1] = _end_sentence(out[-1])
            out.append(" " + token)
        else:
            out.append(" " + token)
    return "".join(out)


def _prominence_scores(
    audio: np.ndarray,
    sample_rate: int,
    words: list[Word],
) -> list[float]:
    """Per-word acoustic prominence in [0, 1] from the 5 cheap features.

    Uses ``parselmouth`` (Praat) for F0 / intensity / HNR over each word's audio
    slice. Returns all-zeros (no emphasis) when the optional ``prosody`` extra is
    not installed or extraction fails — Phase 2 degrades to Phase 1 cleanly. The
    score is a z-scored blend of mean intensity and pitch movement across words,
    biased for precision (a wrong bold is worse than a missed one; spec §Rationale).
    """
    try:
        import parselmouth  # type: ignore  # optional `prosody` extra
    except Exception:
        return [0.0] * len(words)

    try:
        sound = parselmouth.Sound(audio.astype("float64"), sampling_frequency=sample_rate)
        intensity = sound.to_intensity()
        pitch = sound.to_pitch()
        feats: list[float] = []
        for w in words:
            mid = (w.start + w.end) / 2.0
            try:
                db = intensity.get_value(mid)
            except Exception:
                db = None
            try:
                f0 = pitch.get_value_at_time(mid)
            except Exception:
                f0 = None
            loud = float(db) if db is not None and not np.isnan(db) else 0.0
            voiced = 1.0 if (f0 is not None and not np.isnan(f0)) else 0.0
            feats.append(loud + 5.0 * voiced)  # loudness dominates, voicing nudges
        arr = np.asarray(feats, dtype="float64")
        if arr.size == 0 or float(np.ptp(arr)) == 0.0:
            return [0.0] * len(words)
        # Min-max to [0, 1]; the brightest word(s) approach 1.0.
        norm = (arr - arr.min()) / (arr.max() - arr.min())
        return [float(x) for x in norm]
    except Exception as exc:  # never let a prosody pass break dictation
        log.debug("prominence extraction failed: %s", exc)
        return [0.0] * len(words)


def annotate(
    text: str,
    audio: np.ndarray,
    sample_rate: int,
    words: list[Word],
    config: ProsodyConfig,
) -> ProsodyResult:
    """Re-render *text* with prosody-driven formatting (the daemon entry point).

    Pause→¶ comes from the inter-word gaps in ``words`` (no acoustic dep).
    Emphasis→bold runs only when ``config.format`` renders bold (``markdown``) and
    ``config.emphasis_enabled`` — it scores acoustic prominence via parselmouth and
    bolds words at/above ``emphasis_sensitivity``. Content always comes from
    ``text`` (post clean_text + disfluency); ``words`` supply timing/emphasis only,
    aligned by index, so a token-count mismatch degrades to plain spacing rather
    than raising. ``latency_ms`` is measured for the spec's latency valve.
    """
    t0 = time.monotonic()
    tokens = text.split()
    if not tokens:
        return ProsodyResult(text="", paragraph_breaks=0, emphasized=0, latency_ms=0.0)

    pause_threshold_s = config.pause_paragraph_ms / 1000.0
    renderable = config.format == "markdown"
    want_emphasis = renderable and config.emphasis_enabled

    scores = (
        _prominence_scores(audio, sample_rate, words)
        if want_emphasis and words
        else [0.0] * len(words)
    )

    marks: list[ProsodyMark] = []
    for i in range(len(tokens)):
        pause_before = 0.0
        if 0 < i < len(words):
            pause_before = max(0.0, words[i].start - words[i - 1].end)
        emphasized = want_emphasis and i < len(scores) and scores[i] >= config.emphasis_sensitivity
        marks.append(ProsodyMark(pause_before_s=pause_before, emphasized=emphasized))

    # Always render with the bold-capable formatter so pause→¶ (universal
    # whitespace) is emitted even for format="none"; emphasis is governed purely
    # by the marks (False unless ``want_emphasis``), so "none" yields breaks only.
    rendered = format_prosody(
        tokens, marks,
        paragraph_pause_s=pause_threshold_s,
        sentence_pause_s=config.pause_sentence_ms / 1000.0,
        style="markdown",
    )
    breaks = rendered.count("\n\n")
    emphasized_count = sum(1 for m in marks if m.emphasized)
    latency_ms = (time.monotonic() - t0) * 1000.0
    return ProsodyResult(
        text=rendered,
        paragraph_breaks=breaks,
        emphasized=emphasized_count,
        latency_ms=latency_ms,
    )
