"""`yazses tune` must not learn a spelling from another Whisper.

`initial_prompt` priming exists for words Whisper *cannot spell*. Sourcing those
spellings from a re-transcription -- a bigger Whisper's guess -- is circular, and it
fails hardest on exactly the coined words the feature is for.

Measured on a real 1646-event corpus (2026-08-23): all 21 terms the proposal offered
came from `retx_text` and none from a human correction, among them `yasas` -- a
variant of the mis-hearing `stt/vocabulary.py` documents for this app's own name. On
`--apply` that would have primed the decoder toward the broken spelling the built-in
prompt exists to prevent.

`_propose_disfluency` already draws this line; these tests hold the vocabulary
proposal to the same one, and hold it against the *effective* prompt rather than the
configured one.
"""
from __future__ import annotations

import time

from yazses.config import Config
from yazses.learning.analysis import analyze
from yazses.learning.store import EventRecord
from yazses.stt.vocabulary import merge_initial_prompt


def _rec(**kw) -> EventRecord:
    base = dict(
        id=1, ts=time.time(), audio_secs=1.0, decode_ms=50.0, model="base.en",
        level=None, sample_rate=16000, intent_type="dictate", intent_action="inject",
        injected=True, discard_reason=None, wrong_flag=False, edit_signal=None,
        retx_distance=None, has_audio=False, raw_text="", cleaned_text="",
        filtered_text="", final_text="", correction_text="", retx_text="",
    )
    base.update(kw)
    return EventRecord(**base)


def _kinds(events, cfg=None):
    return {p.kind: p for p in analyze(events, cfg or Config())}


# Distinct prefixes, so consecutive events are not read as re-dictations of each
# other. `_augment_with_inferred_corrections` synthesises a `correction_text` from
# the *next* event when two look alike -- with a uniform prefix these fixtures grow
# a human correction they were written not to have, and the test then proves
# nothing. (Caught by mutation: the first version of this file stayed green with
# the fix reverted.)
_PREFIXES = [
    "lets open", "please start", "now launch", "then restart", "quickly reload",
    "kindly close", "finally stop", "again resume", "maybe pause", "just build",
]


def test_a_retranscription_alone_never_proposes_vocabulary():
    """The regression: the live model said one thing, a bigger Whisper said another,
    and no human ever corrected either. That is a model disagreement, not a spelling."""
    events = [
        _rec(id=i, ts=1000.0 + i,
             raw_text=f"{_PREFIXES[i]} {w} on node {i}",
             retx_text=f"{_PREFIXES[i]} yasas on node {i}",
             retx_distance=0.2)
        for i, w in enumerate(["yes ses", "yaz says", "yacht says", "yes says"])
    ]
    # the fixture must be the case under test: a re-transcription and no correction
    from yazses.learning.analysis import _augment_with_inferred_corrections
    assert not any(e.correction_text for e in _augment_with_inferred_corrections(events, Config()))
    assert "vocabulary" not in _kinds(events)


def test_the_same_events_would_have_proposed_it_before():
    """Pins *why* the guard is needed: the term clears every other filter -- it is
    long enough, not a stopword, not a ghost word, and frequent enough. Only the
    source of the spelling disqualifies it."""
    from yazses.learning.analysis import _VOCAB_STOPWORDS, _worth_priming

    assert _worth_priming("yasas")
    assert "yasas" not in _VOCAB_STOPWORDS
    assert len("yasas") > 2


def test_a_human_correction_still_proposes_vocabulary():
    """The feature must keep working on the evidence it was designed for."""
    events = [
        _rec(id=i, ts=1000.0 + i,
             raw_text=f"{_PREFIXES[i]} cubernetes on node {i}",
             correction_text=f"{_PREFIXES[i]} kubernetes on node {i}")
        for i in range(3)
    ]
    props = _kinds(events)
    assert "vocabulary" in props
    assert "kubernetes" in str(props["vocabulary"].value)


def test_a_correction_and_a_retranscription_together_use_the_correction():
    """`correction_text` wins; the re-transcription's spelling must not leak in."""
    events = [
        _rec(id=i, ts=1000.0 + i,
             raw_text=f"{_PREFIXES[i]} cubernetes on node {i}",
             correction_text=f"{_PREFIXES[i]} kubernetes on node {i}",
             retx_text=f"{_PREFIXES[i]} koobernetes on node {i}",
             retx_distance=0.3)
        for i in range(3)
    ]
    value = str(_kinds(events)["vocabulary"].value)
    assert "kubernetes" in value
    assert "koobernetes" not in value


def test_a_term_already_in_the_builtin_prompt_is_not_proposed():
    """`stt/vocabulary.py` always primes the app name, so a proposer reading only
    `[stt] initial_prompt` cannot see it and would offer it again."""
    cfg = Config()
    assert cfg.stt.initial_prompt == ""
    assert "yazses" in (merge_initial_prompt(cfg.stt.initial_prompt) or "").lower()

    events = [
        _rec(id=i, ts=1000.0 + i,
             raw_text=f"{_PREFIXES[i]} yes ses on node {i}",
             correction_text=f"{_PREFIXES[i]} yazses on node {i}")
        for i in range(3)
    ]
    props = _kinds(events, cfg)
    assert "yazses" not in str(props.get("vocabulary", "")).lower()


def test_a_retranscription_cannot_corroborate_a_vocabulary_proposal():
    """Held-out validation must re-apply the *same* signal that produced the proposal.

    If the proposal may only be mined from a human correction but corroboration
    accepts a re-transcription, a term can be reported as "corroborated by N held-out
    events" on evidence the proposer itself would have refused — the held-out set
    stops being an independent check and starts being a weaker one.
    """
    from yazses.learning.analysis import analyze_validated

    # 20 fit events: a real correction supplies "kubernetes".
    fit = [
        _rec(id=i, ts=1000.0 + i,
             raw_text=f"{_PREFIXES[i % len(_PREFIXES)]} cubernetes on node {i}",
             correction_text=f"{_PREFIXES[i % len(_PREFIXES)]} kubernetes on node {i}")
        for i in range(20)
    ]
    # 5 held-out events where only a re-transcription mentions it, never the user.
    held = [
        _rec(id=100 + i, ts=2000.0 + i,
             raw_text=f"{_PREFIXES[i % len(_PREFIXES)]} cubernetes on host {i}",
             retx_text=f"{_PREFIXES[i % len(_PREFIXES)]} kubernetes on host {i}",
             retx_distance=0.2)
        for i in range(5)
    ]
    props = {p.kind: p for p in analyze_validated(fit + held, Config())}
    vocab = props["vocabulary"]
    assert "kubernetes" in str(vocab.value)
    assert vocab.holdout_size == 5
    assert vocab.holdout_support == 0, (
        "a model re-transcription corroborated a proposal the proposer would refuse"
    )
