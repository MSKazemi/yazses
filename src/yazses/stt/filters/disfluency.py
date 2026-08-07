"""Offline disfluency filter — removes filler words, repetitions, and self-corrections."""
from __future__ import annotations

import re
from dataclasses import dataclass

from yazses.config import DisfluencyConfig


@dataclass
class FilterResult:
    text: str
    chars_removed: int


def filter_transcript(text: str, config: DisfluencyConfig | None = None) -> FilterResult:
    """Apply three-pass disfluency filter. Returns cleaned text and chars removed.

    Rule A: filler word removal (case-insensitive word boundary regex).
            Guard: do NOT remove tokens that contain uppercase, underscore, slash, or dot
            (those are proper nouns or code identifiers). Exception: a capitalised filler
            at utterance position 0 is removed — Whisper capitalises sentence starts, so
            leading "Um"/"Uh" would otherwise never be stripped (see #117).
    Rule B: consecutive 2-gram deduplication (repeat until stable).
    Rule B.5: sub-word repetition & prolongation collapse (opt-in; ADR-015).
    Rule C: self-correction trigger detection — if found, remove from last sentence
            boundary before the trigger, through to end of trigger phrase.
    """
    if config is None:
        config = DisfluencyConfig()
    if not config.enabled or not text.strip():
        return FilterResult(text=text, chars_removed=0)

    original_len = len(text)

    # Rule A — filler word removal
    text = _remove_fillers(text, config.filler_words)

    # Rule B — 2-gram consecutive dedup
    text = _dedup_2grams(text)

    # Rule B.5 — sub-word repetition & prolongation collapse (opt-in; ADR-015)
    text = _collapse_dysfluencies(text, config)

    # Rule C — self-correction rollback
    text = _apply_self_corrections(text, config.self_correction_triggers)

    # Normalise multiple spaces
    text = re.sub(r'  +', ' ', text).strip()

    return FilterResult(text=text, chars_removed=max(0, original_len - len(text)))


def _is_protected(token: str) -> bool:
    """Return True if this token should NOT be altered (proper noun or code id)."""
    return bool(
        any(c.isupper() for c in token)
        or '_' in token
        or '/' in token
        or '.' in token
    )


def _is_code_or_path_token(token: str) -> bool:
    """True when the token looks like a code identifier or path/URL fragment."""
    return '_' in token or '/' in token or '.' in token


def _is_utterance_initial(text: str, match_start: int) -> bool:
    """True when ``match_start`` is the first non-whitespace content in ``text``."""
    return not text[:match_start].strip()


def _collapse_prolongations(text: str, min_run: int) -> str:
    """Collapse a run of the same letter of length >= ``min_run`` to one letter.

    Per token; protected tokens (proper nouns / code / URLs) are left untouched.
    English double letters (run length 2) stay safe when ``min_run`` >= 3.
    """
    if min_run < 2:
        return text
    pattern = re.compile(rf'([a-zA-Z])\1{{{min_run - 1},}}')
    out: list[str] = []
    for token in text.split():
        if _is_protected(token):
            out.append(token)
        else:
            out.append(pattern.sub(r'\1', token))
    return ' '.join(out)


def _collapse_repetitions(text: str, max_fragment_len: int) -> str:
    """Collapse stutter repetitions: hyphenated false starts, short fragment
    runs, and heavy unigram repeats. Conservative by design — intentional
    hyphenation (re-read), emphasis pairs (very very), and protected tokens
    are left untouched."""

    def _fix_hyphen(tok: str) -> str:
        if '-' not in tok or _is_protected(tok):
            return tok
        parts = tok.split('-')
        if len(parts) >= 3:  # >= 2 leading fragments + final word
            lead, final = parts[:-1], parts[-1]
            frag = lead[0]
            if final and frag.isalpha() and all(p == frag for p in lead) \
               and final.lower().startswith(frag.lower()):
                return final
        return tok

    tokens = [_fix_hyphen(t) for t in text.split()]
    result: list[str] = []
    i, n = 0, len(tokens)
    while i < n:
        tok = tokens[i]
        # (b) >=2 identical short fragments followed by a longer word they prefix
        if tok.isalpha() and not _is_protected(tok) and len(tok) <= max_fragment_len:
            j = i
            while j < n and tokens[j] == tok:
                j += 1
            if (j - i) >= 2 and j < n and not _is_protected(tokens[j]) \
               and len(tokens[j]) > len(tok) and tokens[j].lower().startswith(tok.lower()):
                result.append(tokens[j])
                i = j + 1
                continue
        # (c) unigram run of length >= 3
        if not _is_protected(tok):
            j = i
            while j < n and tokens[j] == tok:
                j += 1
            if (j - i) >= 3:
                result.append(tok)
                i = j
                continue
        result.append(tok)
        i += 1
    return ' '.join(result)


def _collapse_dysfluencies(text: str, config: DisfluencyConfig) -> str:
    """Opt-in Rule B.5 — sub-word repetition + prolongation collapse (ADR-015)."""
    if config.collapse_repetitions:
        text = _collapse_repetitions(text, config.repetition_max_fragment_len)
    if config.collapse_prolongations:
        text = _collapse_prolongations(text, config.prolongation_min_run)
    return text


def _remove_fillers(text: str, filler_words: list[str]) -> str:
    if not filler_words:
        return text
    # Sort longest first so multi-word fillers match before single words.
    # The trailing \b is load-bearing: without it "like" matched the prefix of
    # "likely" and left "ly" behind, and "actually" was eaten out of the middle
    # of a URL. Every filler is alphabetic, so a word boundary on both sides is
    # always the right anchor.
    sorted_fillers = sorted(filler_words, key=len, reverse=True)
    pattern = re.compile(
        r'\b(' + '|'.join(re.escape(w) for w in sorted_fillers) + r')\b[,]?\s*',
        re.IGNORECASE,
    )

    def _enclosing_token(start: int, end: int) -> str:
        """The whitespace-delimited token(s) the match sits inside."""
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        while end < len(text) and not text[end].isspace():
            end += 1
        return text[start:end]

    def _replacer(m: re.Match) -> str:
        matched = m.group(0)
        # Protect uppercase / code tokens. This must test the *enclosing* token,
        # not the matched filler: "basically" inside "basically_fn" is a bare
        # lowercase word on its own and would sail past the guard, turning a code
        # identifier into "_fn" mid-dictation.
        enclosing = _enclosing_token(m.start(1), m.end(1))
        if _is_protected(enclosing):
            # Exception (issue #117 / option 2): Whisper capitalises the first
            # word of an utterance, so sentence-initial fillers ("Um …") trip
            # the uppercase guard and would otherwise never be removed.
            # Relax the *uppercase* check only for position 0; code/path tokens
            # and mid-utterance capitalised lookalikes ("the Like button") stay
            # protected.
            if _is_code_or_path_token(enclosing) or not _is_utterance_initial(
                text, m.start()
            ):
                return matched
        return ''

    return pattern.sub(_replacer, text)


def _dedup_2grams(text: str) -> str:
    """Remove second occurrence of consecutive identical 2-grams."""
    while True:
        tokens = text.split()
        changed = False
        i = 0
        result: list[str] = []
        while i < len(tokens):
            if (
                i + 3 < len(tokens)
                and tokens[i] == tokens[i + 2]
                and tokens[i + 1] == tokens[i + 3]
            ):
                result.append(tokens[i])
                result.append(tokens[i + 1])
                i += 4
                changed = True
            else:
                result.append(tokens[i])
                i += 1
        text = ' '.join(result)
        if not changed:
            break
    return text


def _apply_self_corrections(text: str, triggers: list[str]) -> str:
    if not triggers:
        return text
    lower = text.lower()
    for trigger in triggers:
        idx = lower.find(trigger.lower())
        if idx == -1:
            continue
        # Find last sentence boundary before the trigger
        boundary = max(
            text.rfind('. ', 0, idx),
            text.rfind('! ', 0, idx),
            text.rfind('? ', 0, idx),
        )
        if boundary == -1:
            # No sentence boundary — remove everything up to end of trigger
            end = idx + len(trigger)
            # Skip trailing whitespace/comma
            while end < len(text) and text[end] in ' ,':
                end += 1
            text = text[end:].strip()
        else:
            # Remove from after the boundary separator through end of trigger
            keep_end = boundary + 2  # keep '. '
            end = idx + len(trigger)
            while end < len(text) and text[end] in ' ,':
                end += 1
            text = text[:keep_end] + text[end:]
        lower = text.lower()
    return text
