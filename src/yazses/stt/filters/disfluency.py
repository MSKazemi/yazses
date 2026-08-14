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
            at utterance position 0 is removed only when it is an unambiguous filler —
            Whisper capitalises sentence starts, so leading "Um"/"Uh" would otherwise
            never be stripped (see #117). Content words like "Right"/"Like" and
            multi-word fillers like "You know" stay protected (see #120).
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


# Sentence punctuation that Whisper hangs off a hesitation ("Uh...", "Um,").
# It is not evidence of a code identifier, so it is trimmed before that check.
_TRAILING_PUNCTUATION = '.,;:!?…'


def _is_code_or_path_token(token: str) -> bool:
    """True when the token looks like a code identifier or path/URL fragment.

    Only a dot *inside* the token counts. Whisper writes a hesitation as
    ``"Uh..."``, and treating that trailing dot like the one in ``main.py`` left
    a leading filler permanently protected (issue #122). ``Actually.`` at the
    end of a sentence stays safe regardless: it is not a hesitation particle,
    so ``_is_unambiguous_filler`` refuses it before this check matters.
    """
    core = token.rstrip(_TRAILING_PUNCTUATION)
    return '_' in core or '/' in core or '.' in core


# Non-lexical hesitation sounds. These are never ordinary English words, which
# is what makes them safe to strip at utterance position 0 despite Whisper's
# capitalisation.
#
# The membership test is lexical, not phonetic: a particle qualifies only when
# it has no dictionary sense outside interjection. "err" looked like it belonged
# here and does not — it is a verb ("to err is human"), so it was removed from
# both this set and the default filler list (issue #125). "ah" stays: it is an
# interjection in every sense, so dropping it costs tone, never meaning.
_HESITATION_PARTICLES = frozenset({'um', 'uh', 'er', 'ah', 'hmm'})


def _is_unambiguous_filler(filler: str) -> bool:
    """True when ``filler`` contains a non-lexical hesitation particle.

    Position 0 is the one place Whisper's capitalisation is uninformative, so
    the uppercase guard is relaxed there — but only for fillers that cannot
    open a real sentence. A filler qualifies when any of its words is a
    hesitation particle, which admits ``"so um"`` / ``"so uh"`` (issue #122)
    while still refusing ``"you know"``, ``"i mean"`` and ``"okay so"``: those
    are three real words that legitimately start a sentence, and deleting one
    is worse than leaving a filler in (issue #120).
    """
    return any(word in _HESITATION_PARTICLES for word in filler.split())


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


def _hyphen_parts(token: str) -> list[str]:
    """The hyphen-separated parts of a token, ignoring surrounding punctuation."""
    core = token.strip(_TRAILING_PUNCTUATION + '"\'()[]')
    return [p for p in core.split('-') if p]


def _is_all_filler_hyphenated(token: str, fillers: frozenset[str]) -> bool:
    """True when every part of a hyphenated token is a filler word.

    ``um-um`` and ``uh-uh`` qualify; ``a-a-actually`` does not, because
    ``actually`` is a real word the user said.
    """
    parts = _hyphen_parts(token)
    return len(parts) > 1 and all(p.lower() in fillers for p in parts)


def _drop_all_filler_hyphen_tokens(text: str, fillers: frozenset[str]) -> str:
    """Remove hyphenated tokens that are nothing but fillers, whole.

    Removing them part-by-part is what left an orphan ``-`` glued to the next
    word (``um-um the meeting`` -> ``-the meeting``).
    """
    kept = [t for t in text.split(' ') if not _is_all_filler_hyphenated(t, fillers)]
    return ' '.join(kept)


def _tidy_orphaned_punctuation(text: str) -> str:
    """Repair punctuation left stranded by removing a filler.

    The filler pattern consumes a comma *after* the word but not before it, so a
    filler that closed a clause left the comma dangling — "this is probably fine,
    you know" became "this is probably fine," and "the tests, you know, are slow"
    became "the tests, are slow". Both are text typed into someone's document, and
    both read as a bug in the tool rather than as speech.

    Only ever applied when the filler pass actually removed something, so text
    nobody touched keeps whatever punctuation was dictated.
    """
    # ", ," -> ","  (filler sat between two commas)
    text = re.sub(r",\s*,", ",", text)
    # " ," -> ","   (the word before the comma was the one removed)
    text = re.sub(r"\s+([,;:])", r"\1", text)
    # a clause separator with nothing left after it
    text = re.sub(r"[,;:]\s*$", "", text)
    return text


def _remove_fillers(text: str, filler_words: list[str]) -> str:
    if not filler_words:
        return text

    # A hyphen is a word boundary, so Rule A would otherwise reach *inside* a
    # hyphenated token and delete one part of it — turning "right-click" into
    # "-click" and, worse, "a-a-actually" (what a stutter looks like once
    # transcribed) into a fragment glued to the next word. Since this filter is
    # the implementation of dysfluency-friendly mode, destroying a stuttered
    # word is the worst possible failure for the user it exists to serve.
    #
    # So hyphenated tokens are handled here, at token level, and never opened
    # up by the regex below: a token that is *entirely* filler is dropped whole,
    # and any other hyphenated token is left exactly as spoken. Collapsing
    # "a-a-actually" to "actually" would be the more ambitious repair, but it
    # cannot be done safely by a filler-removal pass — "w-w-want" proves the
    # repeated fragment is not always a filler — so that belongs to the
    # repetition rules (issue #144).
    fillers = frozenset(w.lower() for w in filler_words)
    text = _drop_all_filler_hyphen_tokens(text, fillers)
    # Sort longest first so multi-word fillers match before single words.
    # The trailing \b is load-bearing: without it "like" matched the prefix of
    # "likely" and left "ly" behind, and "actually" was eaten out of the middle
    # of a URL. Every filler is alphabetic, so a word boundary on both sides is
    # always the right anchor.
    sorted_fillers = sorted(filler_words, key=len, reverse=True)
    # The optional leading `,\s*` matters as much as the trailing one: a filler
    # is often a parenthetical ("the tests, you know, are slow"), and consuming
    # only the closing comma left "the tests, are slow" — a comma between subject
    # and verb, typed into the user's document.
    pattern = re.compile(
        r'(?:,\s*)?\b(' + '|'.join(re.escape(w) for w in sorted_fillers) + r')\b[,]?\s*',
        re.IGNORECASE,
    )

    def _enclosing_token(start: int, end: int) -> str:
        """The whitespace-delimited token(s) the match sits inside."""
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        while end < len(text) and not text[end].isspace():
            end += 1
        return text[start:end]

    # Set when a filler is removed from position 0, so its own trailing
    # punctuation can be cleared afterwards ("Uh... so I think" must not be
    # left as "... so I think"). The regex cannot consume it inside the match
    # without also eating sentence punctuation after a mid-utterance filler.
    removed_leading = False

    def _replacer(m: re.Match) -> str:
        nonlocal removed_leading
        matched = m.group(0)
        # Protect uppercase / code tokens. This must test the *enclosing* token,
        # not the matched filler: "basically" inside "basically_fn" is a bare
        # lowercase word on its own and would sail past the guard, turning a code
        # identifier into "_fn" mid-dictation.
        enclosing = _enclosing_token(m.start(1), m.end(1))
        # Never reach inside a hyphenated token. Anything still containing a
        # hyphen at this point has at least one non-filler part, i.e. a real
        # word the user said; removing the filler part alone would corrupt it.
        if '-' in enclosing.strip(_TRAILING_PUNCTUATION):
            return matched
        at_start = _is_utterance_initial(text, m.start())
        if _is_protected(enclosing):
            # Exception (issue #117 / option 2, narrowed by #120 and #122):
            # Whisper capitalises the first word of an utterance, so
            # sentence-initial fillers ("Um …") trip the uppercase guard and
            # would otherwise never be removed. Relax the *uppercase* check only
            # at position 0, and only for fillers that cannot open a real
            # sentence.
            if (
                _is_code_or_path_token(enclosing)
                or not at_start
                or not _is_unambiguous_filler(m.group(1).lower())
            ):
                return matched
        if at_start:
            removed_leading = True
        # When the match swallowed the parenthetical's opening comma it also
        # swallowed the space in front of it, so returning nothing would glue the
        # neighbours together ("the tests, you know, are slow" -> "the testsare
        # slow"). One space; the collapse pass at the end tidies any doubling.
        return ' ' if matched.lstrip().startswith(',') else ''

    out = pattern.sub(_replacer, text)
    if removed_leading:
        out = out.lstrip(_TRAILING_PUNCTUATION + ' ')
    if out != text:
        out = _tidy_orphaned_punctuation(out)
    return out


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


# Words that, immediately before a self-correction trigger, mean the speaker is
# *talking about* the action rather than performing it. "Please do not delete that
# branch" is an instruction whose whole point is the negation; treating it as a
# rollback deleted the sentence and left the object of the instruction behind
# ("branch"), which is the most dangerous output the filter can produce — it does
# not garble the meaning, it inverts it.
_NEGATIONS_BEFORE_TRIGGER = (
    "not", "don't", "dont", "doesn't", "doesnt", "didn't", "didnt",
    "won't", "wont", "can't", "cant", "cannot", "never", "no",
)


def _trigger_is_negated(lower: str, idx: int) -> bool:
    """True when the trigger at *idx* is governed by a preceding negation.

    Only the word immediately before it is consulted. A wider window would start
    suppressing genuine corrections in long sentences that merely happen to
    contain a "not" somewhere earlier, and a missed rollback is a visible extra
    sentence while a wrong one is silently destroyed meaning.
    """
    before = lower[:idx].rstrip(" ,")
    if not before:
        return False
    return before.rsplit(" ", 1)[-1] in _NEGATIONS_BEFORE_TRIGGER


def _trigger_positions(lower: str, trigger: str):
    """Every position where *trigger* is a real rollback, earliest first.

    ``str.find`` matched anywhere, including inside ordinary prose, so a sentence
    that merely contains the words fired a rollback that discarded everything
    before it. Each candidate is filtered on word boundaries and on whether a
    negation governs it.
    """
    start = 0
    while (idx := lower.find(trigger, start)) != -1:
        start = idx + 1
        before_ok = idx == 0 or not (lower[idx - 1].isalnum() or lower[idx - 1] == "'")
        after = idx + len(trigger)
        after_ok = after >= len(lower) or not (lower[after].isalnum() or lower[after] == "'")
        if before_ok and after_ok and not _trigger_is_negated(lower, idx):
            yield idx


def _apply_self_corrections(text: str, triggers: list[str]) -> str:
    if not triggers:
        return text
    while True:
        lower = text.lower()
        # Resolve the trigger that was *spoken* first, not the one that happens
        # to be declared first in config (#145). Iterating the config list meant
        # "scratch that. no wait …" resolved "no wait" first purely because it
        # sits earlier in the default list, discarding the correction the user
        # actually made first.
        found = min(
            (
                (idx, trigger)
                for trigger in triggers
                for idx in _trigger_positions(lower, trigger.lower())
            ),
            default=None,
        )
        if found is None:
            return text
        idx, trigger = found

        # Find last sentence boundary before the trigger
        boundary = max(
            text.rfind('. ', 0, idx),
            text.rfind('! ', 0, idx),
            text.rfind('? ', 0, idx),
        )
        end = idx + len(trigger)
        # Consume the punctuation that belongs to the trigger clause. Periods
        # were previously left behind, so "delete that." — the ordinary way
        # people phrase it, as a complete sentence — deposited a bare " . " in
        # the middle of the output (#145).
        while end < len(text) and text[end] in ' ,.!?…':
            end += 1
        if boundary == -1:
            # No sentence boundary — remove everything up to end of trigger
            text = text[end:].strip()
        else:
            # Remove from after the boundary separator through end of trigger
            keep_end = boundary + 2  # keep '. '
            text = (text[:keep_end] + text[end:]).strip()
