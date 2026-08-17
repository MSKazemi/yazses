"""Turn the captured corpus into concrete, reviewable tuning proposals.

Nothing here changes config on its own. :func:`analyze` reads events and emits a
list of :class:`Proposal`s; the CLI prints them and only applies the ones the
user approves (``yazses tune --apply``). Every proposal is backed by counted
evidence from real events, never a guess.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from yazses.config import Config
from yazses.learning.store import CorpusStore, EventRecord

log = logging.getLogger(__name__)

# Thresholds governing when a signal is strong enough to surface a proposal.
_MODEL_DISTANCE_TRIGGER = 0.15   # mean word-error vs bigger model to suggest upgrade
_VOCAB_MIN_OCCURRENCES = 2       # term must be missed in >= this many events
_FILLER_MIN_OCCURRENCES = 2
_SMALL_MODELS = ("tiny.en", "tiny", "base.en", "base")
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z'-]*")


@dataclass
class Proposal:
    kind: str                     # vad_threshold | model | vocabulary | disfluency | few_shots
    title: str
    detail: str
    evidence: int                 # number of supporting events
    target: str = "config"        # "config" or "few_shots"
    section: str | None = None    # config.toml section
    key: str | None = None
    value: object = None          # proposed value (number/string/list)
    examples: list[str] = field(default_factory=list)  # for few_shots target
    # Held-out validation (ADR-014): corroborating events from a recent slice the
    # proposal was NOT derived from. ``None`` = not evaluated (corpus too small).
    holdout_support: int | None = None
    holdout_size: int = 0

    @property
    def status(self) -> str:
        """Human-readable validation verdict for display in `yazses tune`."""
        if self.holdout_support is None:
            return "unvalidated (corpus too small to hold out)"
        if self.holdout_size == 0:
            return "unvalidated (no distinct held-out data)"
        if self.holdout_support > 0:
            return f"validated ({self.holdout_support}/{self.holdout_size} held-out)"
        return "unverified — no held-out corroboration"


# --------------------------------------------------------------------------
# Text distance
# --------------------------------------------------------------------------

def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def word_distance(a: str, b: str) -> float:
    """Word-level Levenshtein distance normalized to [0, 1].

    0.0 = identical word sequences; 1.0 = completely different.
    """
    wa, wb = _tokens(a), _tokens(b)
    if not wa and not wb:
        return 0.0
    if not wa or not wb:
        return 1.0
    prev = list(range(len(wb) + 1))
    for i, ta in enumerate(wa, 1):
        cur = [i]
        for j, tb in enumerate(wb, 1):
            cost = 0 if ta == tb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1] / max(len(wa), len(wb))


# --------------------------------------------------------------------------
# Re-transcription (offline pseudo-ground-truth)
# --------------------------------------------------------------------------

TranscribeFn = Callable[["object", int], str]


def retranscribe(
    store: CorpusStore,
    transcribe_fn: TranscribeFn,
    limit: int | None = None,
    progress: "Callable[[int, int], None] | None" = None,
) -> int:
    """Re-run captured audio through a (larger) model, storing distance vs raw.

    ``transcribe_fn(audio, sample_rate) -> str`` is injected so tests need no
    real model. Only events that have audio and no prior re-transcription are
    processed. Returns the number of events updated.

    ``progress(done, total)`` is called once with ``(0, total)`` before any audio
    is touched and again after each clip. This is the slow step of `yazses tune`
    by a wide margin -- thousands of clips through a larger model on CPU -- and it
    used to report nothing until it finished, so a real corpus looked like a hang.
    The candidates are known from metadata alone, so the total costs nothing.
    """
    candidates = [r for r in store.events() if r.has_audio and not r.retx_text]
    total = len(candidates) if limit is None else min(limit, len(candidates))
    if progress is not None:
        progress(0, total)
    updated = 0
    for rec in candidates:
        if limit is not None and updated >= limit:
            break
        loaded = store.load_audio(rec.id)
        if loaded is None:
            continue
        audio, sr = loaded
        try:
            text = transcribe_fn(audio, sr)
        except Exception:
            log.warning("Re-transcription failed for event %d", rec.id, exc_info=True)
            continue
        store.set_retx(rec.id, text, word_distance(rec.raw_text, text))
        updated += 1
        if progress is not None:
            progress(updated, total)
    return updated


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

# Two consecutive utterances this far apart (seconds) are unrelated, not a redo.
_EDIT_WINDOW_S = 45.0
# Character-level normalized distance at/below which the follow-up looks like a
# re-dictation/correction of the previous utterance (small edit = homophone or
# typo fix like "cubernetes" → "kubernetes"; a different command edits far more).
_REDICTATION_MAX_CHAR_DISTANCE = 0.35


def _event_text(e: EventRecord) -> str:
    """The most representative text for an event (post-filter, else earlier stages)."""
    return e.filtered_text or e.final_text or e.cleaned_text or e.raw_text


def _char_distance(a: str, b: str) -> float:
    """Character-level Levenshtein distance, normalized to [0, 1] (case-insensitive)."""
    a, b = a.lower().strip(), b.lower().strip()
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1] / max(len(a), len(b))


def compute_edit_signals(events: list[EventRecord], config: Config) -> dict[int, float]:
    """Infer that event N was a misrecognition from event N+1 (passive heuristic).

    Two cues, no keystroke capture: (1) the next utterance opens with a
    self-correction trigger ("scratch that", "no wait", …); (2) the next
    utterance closely repeats this one within a short window (a re-dictation).
    Returns ``{event_id: signal_strength in (0, 1]}``.
    """
    triggers = [t.lower() for t in config.filters.disfluency.self_correction_triggers]
    signals: dict[int, float] = {}
    for a, b in zip(events, events[1:]):
        a_text, b_text = _event_text(a), _event_text(b)
        if not a_text.strip() or (b.ts - a.ts) > _EDIT_WINDOW_S:
            continue
        b_lower = b_text.lower().strip()
        if any(b_lower.startswith(t) for t in triggers):
            signals[a.id] = 1.0
            continue
        dist = _char_distance(a_text, b_text)
        if 0.0 < dist <= _REDICTATION_MAX_CHAR_DISTANCE:
            signals[a.id] = round(1.0 - dist, 3)
    return signals


def _augment_with_inferred_corrections(
    events: list[EventRecord], config: Config
) -> list[EventRecord]:
    """Attach inferred correction text + edit_signal so a re-dictation feeds the
    same proposals an explicit `mark-wrong` correction would."""
    signals = compute_edit_signals(events, config)
    if not signals:
        return events
    out: list[EventRecord] = []
    for i, e in enumerate(events):
        sig = signals.get(e.id)
        if not sig:
            out.append(e)
            continue
        correction = e.correction_text
        if not correction and i + 1 < len(events):
            correction = _event_text(events[i + 1])
        out.append(replace(e, edit_signal=sig, correction_text=correction))
    return out


def analyze(events: list[EventRecord], config: Config) -> list[Proposal]:
    """Produce ranked tuning proposals from captured events."""
    events = _augment_with_inferred_corrections(events, config)
    proposals: list[Proposal] = []
    p = _propose_vad(events, config)
    if p:
        proposals.append(p)
    p = _propose_model(events, config)
    if p:
        proposals.append(p)
    p = _propose_vocabulary(events, config)
    if p:
        proposals.append(p)
    p = _propose_disfluency(events, config)
    if p:
        proposals.append(p)
    p = _propose_few_shots(events, config)
    if p:
        proposals.append(p)
    # Strongest evidence first.
    proposals.sort(key=lambda x: x.evidence, reverse=True)
    return proposals


# --------------------------------------------------------------------------
# Held-out validation (ADR-014)
# --------------------------------------------------------------------------

# Defaults: hold out the most recent fifth of the corpus, but only once there
# are enough events that removing a slice still leaves a usable fit set.
_DEFAULT_HOLDOUT_FRACTION = 0.2
_DEFAULT_MIN_CORPUS = 20


def _norm(text: str) -> str:
    return " ".join(_tokens(text))


def _holdout_support(proposal: Proposal, holdout: list[EventRecord], config: Config) -> int:
    """Count held-out events that independently corroborate *proposal*.

    Re-applies the same signal that produced the proposal to events it was never
    derived from. A high count means the change reflects a stable pattern, not an
    artefact of the data it was fit to.
    """
    if proposal.kind == "vocabulary":
        new_terms = set(_tokens(str(proposal.value))) - set(_tokens(config.stt.initial_prompt))
        n = 0
        for e in holdout:
            better = _better_text(e)
            if not better:
                continue
            raw = set(_tokens(e.raw_text))
            bt = set(_tokens(better))
            if any(t in bt and t not in raw for t in new_terms):
                n += 1
        return n
    if proposal.kind == "model":
        return sum(
            1 for e in holdout
            if e.retx_distance is not None and e.retx_distance >= _MODEL_DISTANCE_TRIGGER
        )
    if proposal.kind == "vad_threshold":
        return sum(1 for e in holdout if e.discard_reason == "silent" and e.level)
    if proposal.kind == "disfluency":
        existing = {w.lower() for w in config.filters.disfluency.filler_words}
        proposed = proposal.value if isinstance(proposal.value, (list, tuple)) else []
        new_fillers = {str(w).lower() for w in proposed} - existing
        n = 0
        for e in holdout:
            flagged = e.wrong_flag or (e.edit_signal or 0) > 0
            if not (flagged and e.correction_text):
                continue
            corrected = set(_tokens(e.correction_text))
            if any(tok in new_fillers and tok not in corrected for tok in _tokens(e.raw_text)):
                n += 1
        return n
    if proposal.kind == "few_shots":
        return sum(
            1 for e in holdout
            if e.wrong_flag and e.intent_type and e.intent_type != "dictate" and e.raw_text
        )
    return 0


def analyze_validated(
    events: list[EventRecord],
    config: Config,
    *,
    holdout_fraction: float = _DEFAULT_HOLDOUT_FRACTION,
    min_corpus: int = _DEFAULT_MIN_CORPUS,
) -> list[Proposal]:
    """Like :func:`analyze`, but each proposal is checked on held-out events.

    The corpus is ordered by time; the most recent ``holdout_fraction`` becomes a
    held-out set, proposals are generated from the older remainder, and each is
    re-scored on the held-out events it never saw (``Proposal.holdout_support`` /
    ``holdout_size``). Below ``min_corpus`` events there is too little data to
    split, so proposals are produced from the full set and left ``holdout_support
    = None`` (status: "unvalidated"). See ADR-014.
    """
    events = list(events)
    if len(events) < min_corpus:
        # Too small to hold out; surface proposals but mark them unvalidated.
        return analyze(events, config)

    ordered = sorted(events, key=lambda e: e.ts)
    k = max(1, int(len(ordered) * holdout_fraction))
    fit, holdout = ordered[:-k], ordered[-k:]

    # Leakage guard: a held-out event whose text duplicates a fit event would
    # corroborate trivially — drop it so the split stays honest.
    fit_texts = {_norm(_event_text(e)) for e in fit}
    holdout = [e for e in holdout if _norm(_event_text(e)) not in fit_texts]

    proposals = analyze(fit, config)
    for p in proposals:
        p.holdout_size = len(holdout)
        p.holdout_support = _holdout_support(p, holdout, config)

    # Corroborated proposals first, then by raw evidence.
    proposals.sort(key=lambda p: (p.holdout_support or 0, p.evidence), reverse=True)
    return proposals


def _propose_vad(events: list[EventRecord], config: Config) -> Proposal | None:
    silent_levels = [e.level for e in events if e.discard_reason == "silent" and e.level]
    if not silent_levels:
        return None
    current = config.accessibility.vad_threshold
    # Drop just below the loudest clip we wrongly discarded, with a little
    # headroom, but never below the noise floor. Only worth proposing if it
    # would actually let those clips through.
    recommended = round(max(0.002, max(silent_levels) * 0.9), 4)
    if recommended >= current:
        return None
    accepted = [e.level for e in events if e.injected and e.level]
    accepted_note = (
        f" Quietest accepted speech was {min(accepted):.4f}."
        if accepted else ""
    )
    return Proposal(
        kind="vad_threshold",
        title="Lower the VAD threshold",
        detail=(
            f"{len(silent_levels)} clip(s) were discarded as silent (up to level "
            f"{max(silent_levels):.4f}).{accepted_note} If those were real speech, "
            f"lowering vad_threshold {current} → {recommended} would capture them. "
            "Review — too low and room noise triggers spurious transcripts."
        ),
        evidence=len(silent_levels),
        section="accessibility",
        key="vad_threshold",
        value=recommended,
    )


def _propose_model(events: list[EventRecord], config: Config) -> Proposal | None:
    scored = [e.retx_distance for e in events if e.retx_distance is not None]
    if len(scored) < 3:
        return None
    mean_dist = sum(scored) / len(scored)
    if mean_dist < _MODEL_DISTANCE_TRIGGER or config.stt.model not in _SMALL_MODELS:
        return None
    target_model = config.learning.tune_model or "small.en"
    return Proposal(
        kind="model",
        title="Upgrade the STT model",
        detail=(
            f"A larger model disagreed with '{config.stt.model}' on "
            f"{mean_dist:.0%} of words across {len(scored)} clip(s). Switching to "
            f"'{target_model}' should improve accuracy (at higher CPU cost)."
        ),
        evidence=len(scored),
        section="stt",
        key="model",
        value=target_model,
    )


def _better_text(e: EventRecord) -> str:
    """The most trustworthy 'correct' text for an event, if any."""
    if e.correction_text:
        return e.correction_text
    if e.retx_text and e.retx_distance and e.retx_distance > 0:
        return e.retx_text
    return ""


def _propose_vocabulary(events: list[EventRecord], config: Config) -> Proposal | None:
    # Words present in the corrected/re-transcribed text but missing from what
    # the live model produced — i.e. terms it consistently fails to hear.
    missed: Counter[str] = Counter()
    existing = set(_tokens(config.stt.initial_prompt))
    for e in events:
        better = _better_text(e)
        if not better:
            continue
        raw_tokens = set(_tokens(e.raw_text))
        for tok in _tokens(better):
            if tok not in raw_tokens and tok not in existing and len(tok) > 2:
                missed[tok] += 1
    terms = [w for w, n in missed.most_common() if n >= _VOCAB_MIN_OCCURRENCES]
    if not terms:
        return None
    combined = " ".join(filter(None, [config.stt.initial_prompt, " ".join(terms)]))
    return Proposal(
        kind="vocabulary",
        title="Add vocabulary to the Whisper prompt",
        detail=(
            f"{len(terms)} term(s) were repeatedly mis-transcribed and corrected: "
            f"{', '.join(terms)}. Priming them via initial_prompt helps Whisper "
            "spell them right."
        ),
        evidence=sum(missed[t] for t in terms),
        section="stt",
        key="initial_prompt",
        value=combined,
    )


def _propose_disfluency(events: list[EventRecord], config: Config) -> Proposal | None:
    # Words the user's correction removed from a wrong event — candidate fillers.
    existing = {w.lower() for w in config.filters.disfluency.filler_words}
    removed: Counter[str] = Counter()
    for e in events:
        # Explicit mark-wrong, or an inferred re-dictation correction (signal a).
        flagged = e.wrong_flag or (e.edit_signal or 0) > 0
        if not (flagged and e.correction_text):
            continue
        corrected = set(_tokens(e.correction_text))
        for tok in _tokens(e.raw_text):
            if tok not in corrected and tok not in existing:
                removed[tok] += 1
    candidates = [w for w, n in removed.most_common() if n >= _FILLER_MIN_OCCURRENCES]
    if not candidates:
        return None
    new_list = list(config.filters.disfluency.filler_words) + candidates
    return Proposal(
        kind="disfluency",
        title="Add filler words to the disfluency filter",
        detail=(
            f"These word(s) were removed in your corrections across multiple "
            f"events and look like fillers: {', '.join(candidates)}. Review before "
            "applying — adding a real word here would wrongly strip it."
        ),
        evidence=sum(removed[c] for c in candidates),
        section="filters.disfluency",
        key="filler_words",
        value=new_list,
    )


def _propose_few_shots(events: list[EventRecord], config: Config) -> Proposal | None:
    # False-positive commands: a command fired but the user flagged it wrong.
    # Teach the SLM these utterances are plain dictation.
    examples: list[str] = []
    for e in events:
        if e.wrong_flag and e.intent_type and e.intent_type != "dictate" and e.raw_text:
            examples.append(
                f'"{e.raw_text}" -> '
                '{"intent": "dictate", "action": "inject", "args": {}, "confidence": 0.95}'
            )
    if not examples:
        return None
    return Proposal(
        kind="few_shots",
        title="Add SLM few-shot examples for misfired commands",
        detail=(
            f"{len(examples)} utterance(s) were wrongly classified as commands. "
            "Adding them as dictation few-shots makes the SLM router less trigger-happy."
        ),
        evidence=len(examples),
        target="few_shots",
        examples=examples,
    )


# --------------------------------------------------------------------------
# Applying proposals
# --------------------------------------------------------------------------

def toml_literal(value: object) -> str:
    """Render a Python value as a TOML scalar/array literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_literal(v) for v in value) + "]"
    raise TypeError(f"unsupported TOML value: {value!r}")


def set_toml_key(path: Path, section: str, key: str, value: object) -> str:
    """Set ``[section] key = value`` in a TOML file, preserving comments.

    Replaces an existing assignment of ``key`` if present; otherwise inserts it
    under ``[section]`` (creating the section, or the whole file, as needed).
    Returns a short description of what changed.
    """
    literal = toml_literal(value)
    line = f"{key} = {literal}"
    header = f"[{section}]"

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{header}\n{line}\n")
        return f"created {path} with [{section}] {key}"

    text = path.read_text()
    new_text, n = re.subn(
        rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=.*$", line, text
    )
    if n:
        path.write_text(new_text)
        return f"updated {key}"

    if re.search(rf"(?m)^\[{re.escape(section)}\]\s*$", text):
        new_text = re.sub(
            rf"(?m)^(\[{re.escape(section)}\]\s*)$", r"\1\n" + line, text, count=1
        )
    else:
        sep = "" if text.endswith("\n") or not text else "\n"
        new_text = f"{text}{sep}\n{header}\n{line}\n"
    path.write_text(new_text)
    return f"added [{section}] {key}"


def apply_proposal(proposal: Proposal, config_path: Path, few_shots_path: Path) -> str:
    """Apply an approved proposal to disk and return a description."""
    if proposal.target == "few_shots":
        few_shots_path.parent.mkdir(parents=True, exist_ok=True)
        existing = few_shots_path.read_text() if few_shots_path.exists() else (
            "# YazSes SLM few-shot examples (auto-proposed by `yazses tune`).\n"
            "# One example per line, in the SLM router's classification format.\n"
        )
        block = "\n".join(proposal.examples)
        few_shots_path.write_text(existing.rstrip("\n") + "\n" + block + "\n")
        return f"appended {len(proposal.examples)} few-shot example(s) to {few_shots_path}"
    assert proposal.section and proposal.key is not None
    return set_toml_key(config_path, proposal.section, proposal.key, proposal.value)


def load_few_shots(path: Path) -> list[str]:
    """Read non-comment example lines from a few-shots file (empty if absent)."""
    if not path.exists():
        return []
    return [
        ln.strip()
        for ln in path.read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
