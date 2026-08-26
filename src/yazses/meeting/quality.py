"""Is this transcript worth keeping? — decode-collapse detection for Meeting Mode.

Meeting Mode's post-pass hands a whole recording to Whisper in one batch. When that
decode collapses into a repetition loop — the well-known failure where the model emits
one phrase for the rest of the file — the result is a *syntactically perfect* transcript
of words nobody said, and every existing guard passes it: ``capture_state`` asks whether
audio was **heard** (it was), ``attribution_suspect`` asks who said what (nothing was
mis-attributed, there is only one speaker). ``status`` reached ``"done"``, so the
recording was deleted as a successful consumption, and the meeting became unrecoverable.

Measured on this machine's five stored meetings, the collapse is not a marginal call:

===================  ========  ========  ============  ===========
meeting              duration  words/min  top trigram   distinct
===================  ========  ========  ============  ===========
20260710-212029        56.7 s     106.9        0.0101       1.0000
20260803-095635      8081.4 s     117.9        0.0049       0.8210
20260826-100205      2499.7 s       6.8      **0.9681**   **0.0355**
===================  ========  ========  ============  ===========

Two orders of magnitude between the collapsed decode and the worst healthy one, so the
thresholds sit far from both edges rather than being tuned to the single bad sample.

The **strongest** signal is not in this table and needs no threshold at all: Meeting Mode
already decodes the same audio a second time, incrementally, into ``live.jsonl``. On the
collapsed meeting the live transcript holds 4553 words against the batch pass's 284 — a
16× disagreement between two decodes of one recording, where the healthy 2 h meeting
agrees to within 0.8%. A second opinion beats any statistic computed from one.

Everything here is pure (stdlib only, no models, no I/O) so the policy is testable
against real transcripts without a decode.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

# --- verdicts -------------------------------------------------------------------
QUALITY_OK = "ok"
QUALITY_DEGENERATE = "degenerate"   # the decode collapsed into a repetition loop
QUALITY_THIN = "thin"               # a long recording that produced almost no words
QUALITY_UNJUDGED = "unjudged"       # too little material to make any claim

# --- thresholds (see the module docstring for the measurements behind them) ------
NGRAM = 3
# Below this there is not enough material for a repetition statistic to mean anything.
# The 56.7 s meeting above clears it with 99 trigrams; a 1-word accidental start does
# not, and is deliberately reported as UNJUDGED rather than OK — "we did not look" and
# "we looked and it was fine" are different facts, and only one of them is reassuring.
MIN_NGRAMS = 40
# Worst healthy sample: 0.0101. Collapsed sample: 0.9681. 20x clear of the healthy edge.
MAX_TOP_NGRAM_SHARE = 0.20
# Worst healthy sample: 0.8210. Collapsed sample: 0.0355. Well clear of both.
MIN_DISTINCT_NGRAM_RATIO = 0.35
# A phrase repeated back-to-back this many times is a loop whatever the ratios say —
# it catches a collapse that begins late in a long, otherwise healthy meeting, where
# the whole-transcript averages stay comfortably inside the thresholds above.
MAX_REPEAT_RUN = 12
# "Thin" needs a long recording to be meaningful: a 30 s clip holding one word is an
# accidental start, already described by `capture_state`, and calling it thin as well
# is a second word for a fact the user has been told. Slow, sparse conversation runs
# ~60-80 wpm; the healthy samples above run ~107-118.
THIN_MIN_DURATION_S = 300.0
THIN_MAX_WPM = 25.0
# The live transcript is a second decode of the same audio. This much more content in
# it than in the batch pass means the batch pass lost the meeting, not that the live
# pass was chatty: the healthy 2 h meeting agrees to 1.008x, the collapsed one to 16x.
LIVE_DISAGREEMENT_RATIO = 3.0
# Below this the batch transcript is too small for a ratio to be stable (a 2-word batch
# result and a 7-word live one is a 3.5x "disagreement" about nothing).
LIVE_MIN_BATCH_WORDS = 20

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


@dataclass(frozen=True)
class TranscriptQuality:
    """What the numbers say about a finished transcript. Serialisable as-is."""

    verdict: str = QUALITY_UNJUDGED
    words: int = 0
    duration_s: float = 0.0
    words_per_minute: float = 0.0
    top_ngram_share: float = 0.0
    distinct_ngram_ratio: float = 1.0
    longest_repeat_run: int = 0
    live_words: int = 0
    live_ratio: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def suspect(self) -> bool:
        """True when this transcript must not be treated as a finished good result.

        The one place the question "may the recording be deleted / may notes be
        generated / must the user be warned" is answered, so those three cannot drift
        apart. ``UNJUDGED`` is **not** suspect: it is the ordinary state of a very
        short meeting, and treating it as a failure would keep every stray recording
        forever and warn about all of them.
        """
        return self.verdict in (QUALITY_DEGENERATE, QUALITY_THIN) or self.live_disagrees

    @property
    def live_disagrees(self) -> bool:
        """True when the rolling live decode found substantially more than the batch."""
        return (
            self.words >= LIVE_MIN_BATCH_WORDS
            and self.live_ratio >= LIVE_DISAGREEMENT_RATIO
        )

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "words": self.words,
            "duration_s": round(self.duration_s, 1),
            "words_per_minute": round(self.words_per_minute, 2),
            "top_ngram_share": round(self.top_ngram_share, 4),
            "distinct_ngram_ratio": round(self.distinct_ngram_ratio, 4),
            "longest_repeat_run": self.longest_repeat_run,
            "live_words": self.live_words,
            "live_ratio": round(self.live_ratio, 3),
            "suspect": self.suspect,
            "live_disagrees": self.live_disagrees,
            "reasons": list(self.reasons),
        }


def tokenize(text: str) -> list[str]:
    """Lowercased word tokens, punctuation and digits dropped. Pure.

    NFKC first so a transcript carrying composed and decomposed forms of the same word
    does not read as two distinct words and inflate the distinct-ngram ratio — which
    would make a *degenerate* transcript look healthier, the wrong direction to fail in.
    """
    return _WORD_RE.findall(unicodedata.normalize("NFKC", text or "").lower())


def _ngrams(tokens: list[str], n: int = NGRAM) -> list[tuple[str, ...]]:
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def longest_repeat_run(grams: list[tuple[str, ...]]) -> int:
    """Longest run of one n-gram repeating back-to-back. Pure, O(n).

    Counts *consecutive* repetition rather than total frequency, because a transcript
    that says "thank you" twenty times across an hour is a normal meeting and one that
    says it twenty times in a row is a loop.
    """
    best = run = 0
    prev = None
    for g in grams:
        run = run + 1 if g == prev else 1
        prev = g
        if run > best:
            best = run
    return best


def assess(text: str, duration_s: float = 0.0, live_words: int = 0) -> TranscriptQuality:
    """Judge a finished transcript. Pure — no I/O, no models, never raises.

    ``live_words`` is the word count of the rolling ``live.jsonl`` decode of the same
    audio, or 0 when there is none. It is compared, never merged: the two transcripts
    stay separate artefacts on disk and the user is told which one to read.
    """
    # Both coerced defensively: `assess` is called from the finalize path, where a bad
    # value in one argument must not be able to take the transcript down with it. A
    # non-numeric argument means "we do not know", which is 0 — never an exception.
    try:
        duration_s = max(0.0, float(duration_s or 0.0))
    except (TypeError, ValueError):
        duration_s = 0.0
    try:
        live_words = max(0, int(live_words or 0))
    except (TypeError, ValueError):
        live_words = 0

    tokens = tokenize(text)
    words = len(tokens)
    wpm = (words / (duration_s / 60.0)) if duration_s > 0 else 0.0
    live_ratio = (live_words / words) if words else 0.0

    grams = _ngrams(tokens)
    reasons: list[str] = []
    top_share = 0.0
    distinct = 1.0
    run = 0

    if len(grams) >= MIN_NGRAMS:
        counts = Counter(grams)
        top_share = counts.most_common(1)[0][1] / len(grams)
        distinct = len(counts) / len(grams)
        run = longest_repeat_run(grams)
        if top_share >= MAX_TOP_NGRAM_SHARE:
            reasons.append(
                f"one phrase is {top_share:.0%} of the transcript "
                f"(a healthy decode stays under {MAX_TOP_NGRAM_SHARE:.0%})"
            )
        if distinct <= MIN_DISTINCT_NGRAM_RATIO:
            reasons.append(
                f"only {distinct:.1%} of its phrases are distinct "
                f"(a healthy decode stays above {MIN_DISTINCT_NGRAM_RATIO:.0%})"
            )
        if run >= MAX_REPEAT_RUN:
            reasons.append(f"one phrase repeats {run} times back-to-back")
        verdict = QUALITY_DEGENERATE if reasons else QUALITY_OK
    else:
        verdict = QUALITY_UNJUDGED

    # Thin is checked even when the repetition statistics were unjudged: a long
    # recording that decoded to four words has too few n-grams to test for a loop and
    # is still plainly wrong. It never *overrides* degenerate — a collapse is the more
    # specific diagnosis and names the remedy.
    if verdict != QUALITY_DEGENERATE and duration_s >= THIN_MIN_DURATION_S and wpm < THIN_MAX_WPM:
        reasons.append(
            f"{words} word(s) from {duration_s / 60:.0f} minutes of audio "
            f"({wpm:.1f} words/min) — far below conversational speech"
        )
        verdict = QUALITY_THIN

    q = TranscriptQuality(
        verdict=verdict,
        words=words,
        duration_s=duration_s,
        words_per_minute=wpm,
        top_ngram_share=top_share,
        distinct_ngram_ratio=distinct,
        longest_repeat_run=run,
        live_words=live_words,
        live_ratio=live_ratio,
        reasons=reasons,
    )
    if q.live_disagrees:
        # Appended after construction so the ratio is computed once, in one place.
        return TranscriptQuality(
            **{
                **q.__dict__,
                "reasons": [
                    *reasons,
                    f"the live transcript of the same audio holds {live_words} words "
                    f"against this pass's {words} ({live_ratio:.1f}x) — the batch decode "
                    f"lost most of the meeting",
                ],
            }
        )
    return q


def warning(q: TranscriptQuality) -> str | None:
    """One user-facing line naming the problem and the surviving artefact, else None.

    Phrased around what the reader should do next, not around the metric that fired:
    the numbers are kept in ``quality.json`` for analysis, and a person who has just
    finished a meeting needs to know which file to open.
    """
    if not q.suspect:
        return None
    if q.verdict == QUALITY_DEGENERATE:
        head = (
            "⚠ the batch transcript collapsed into a repetition loop — it is NOT a "
            "record of what was said."
        )
    elif q.verdict == QUALITY_THIN:
        head = (
            "⚠ the batch transcript holds almost no words for a recording this long — "
            "it is unlikely to be a usable record."
        )
    else:
        head = (
            "⚠ the batch transcript disagrees sharply with the live transcript of the "
            "same audio and is likely to have lost most of the meeting."
        )
    tail = (
        f" The live transcript ({q.live_words} words) is the better record — see "
        "live-transcript.md."
        if q.live_words > q.words
        else " The recording has been kept so the post-pass can be retried."
    )
    return head + tail


def from_dict(data: dict) -> TranscriptQuality:
    """Rebuild a :class:`TranscriptQuality` from ``quality.json``. Never raises.

    Unknown keys are dropped rather than raising, so a ``quality.json`` written by a
    newer version can still be read by an older one — this file is a record kept for
    later analysis, and a record that becomes unreadable when the schema grows is not
    one. ``suspect``/``live_disagrees`` are recomputed from the numbers rather than
    trusted from the file, so the stored verdict and the live policy cannot disagree.
    """
    fields = TranscriptQuality.__dataclass_fields__
    kwargs = {k: v for k, v in (data or {}).items() if k in fields}
    kwargs.pop("suspect", None)
    kwargs.pop("live_disagrees", None)
    try:
        return TranscriptQuality(**kwargs)
    except TypeError:  # pragma: no cover - a value of the wrong type in a stored file
        return TranscriptQuality()


def warning_from_dict(data: dict) -> str | None:
    """``warning()`` applied to a stored ``quality.json`` payload. Never raises."""
    return warning(from_dict(data))
