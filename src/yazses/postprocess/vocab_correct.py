"""Recover personal-vocabulary words the recogniser mis-heard (#73).

`initial_prompt` is a Whisper concept. With `[stt] engine = "parakeet"` the
personal dictionary, the built-in name, and `[stt] initial_prompt` are all
silently dropped — so the one fix a user has for names, jargon and code
identifiers stops working the moment they switch engines for its speed.

This is the issue's **approach 2**: post-decode correction, chosen first because
it is engine-agnostic (it helps Whisper too), needs no upstream change, and is
measurable. Decode-time boosting is the better long-term answer and is not
foreclosed by this — it would replace the mechanism, not the vocabulary source.

## What makes this safe enough to ship

Rewriting a user's transcript is dangerous: a correction that fires on ordinary
speech is worse than the mis-hearing it fixes, because the user cannot see what
was changed. Four guards, in order of how much work they do:

1. **Phonetic key must match exactly.** Not "is close" — equal. `~soundex`-style
   reduction collapses vowels and voiced/unvoiced pairs, so "kubernetes" and
   "cooper netties" reduce alike, while "cat" and "dog" cannot.
2. **Edit distance must still be small** relative to length. The phonetic key is
   lossy by design, so it alone would map genuinely different words together;
   the distance check is what stops that.
3. **Short tokens are never corrected.** Below four characters the key space is
   too crowded — "an" would match "Ann".
4. **A token that already *is* a vocabulary word is left alone**, so a correct
   transcript is a fixed point: running this twice changes nothing.

Multi-word terms are matched over a sliding window, longest first, because "cooper
netties" is two tokens and "kubernetes" is one — the interesting cases are
exactly the ones a per-token pass cannot see.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Consonant classes that a recogniser most often swaps. Collapsing them is what
# lets "netties"/"netes" and "ph"/"f" reduce to the same key.
_CLASSES = {
    "b": "1", "p": "1", "f": "1", "v": "1",
    "c": "2", "g": "2", "j": "2", "k": "2", "q": "2", "s": "2", "x": "2", "z": "2",
    "d": "3", "t": "3",
    "l": "4",
    "m": "5", "n": "5",
    "r": "6",
}

_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)

# Very common words that may not take part in a MULTI-token match.
#
# Joining adjacent words is inherently riskier than fixing one mangled token,
# because ordinary English can reassemble into anything: running this over the
# project's docs with a control vocabulary turned "from this", "from its" and
# "from tags" into "Prometheus" — f and p share a phonetic class, so `fromthis`
# and `prometheus` reduce to the same key, and the relaxed budget let it through.
# A split word ("cooper netties") is made of fragments, not of stopwords, so
# excluding these costs the feature nothing and removes the whole class.
_STOPWORDS = frozenset("""
a an and are as at be been but by for from had has have he her his i if in into is it
its of on or she that the their them then there these they this to was were what when
which who will with would you your our us not no so do does did can could should
""".split())

# Longest multi-word vocabulary entry we will try to reassemble from a transcript.
_MAX_PHRASE_TOKENS = 4

# Defaults; both overridable per call.
DEFAULT_MAX_DISTANCE_RATIO = 0.34
MIN_TOKEN_LENGTH = 4


def phonetic_key(word: str) -> str:
    """A lossy, order-preserving consonant sketch of *word*.

    Deliberately simpler than Metaphone and dependency-free: vowels are dropped
    after the first letter, consonants map to a class digit, and runs of the same
    class collapse. `h` and `w` are dropped entirely — they are the letters a
    recogniser is least reliable about.
    """
    letters = [c for c in word.lower() if c.isalpha()]
    if not letters:
        return ""
    head, rest = letters[0], letters[1:]
    # The first letter is encoded by CLASS, not kept literally as Soundex does.
    # Soundex's rule exists to keep names alphabetised; here it defeats the whole
    # purpose, because the single most common substitution in this domain is
    # exactly the one it preserves: "kubernetes" heard as "cubernetties" differs
    # only in k/c, and every later character already matched.
    head_code = _CLASSES.get(head) or ("V" if head in "aeiou" else head)
    out: list[str] = []
    previous = _CLASSES.get(head, "")
    for char in rest:
        if char in "hw":
            continue
        code = _CLASSES.get(char, "")
        if code and code != previous:
            out.append(code)
        if char not in "aeiouy":
            previous = code
        else:
            previous = ""          # a vowel breaks a run, so "tt" ≠ "tot"
    return head_code + "".join(out)


def _distance(a: str, b: str) -> int:
    """Levenshtein distance. Small inputs, so the simple DP is right."""
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(
                previous[j] + 1,        # deletion
                current[j - 1] + 1,     # insertion
                previous[j - 1] + (ca != cb),
            ))
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class Correction:
    """One replacement made, for logging and for the learning corpus."""

    heard: str
    corrected: str
    start: int
    end: int


def _without_possessive(token: str) -> str:
    """Strip a trailing English possessive, if any. Pure."""
    for suffix in ("'s", "\u2019s", "'S", "\u2019S"):
        if token.endswith(suffix) and len(token) > len(suffix):
            return token[: -len(suffix)]
    return token


def _is_close(heard: str, term: str, max_ratio: float) -> bool:
    """Both guards: identical phonetic key AND a small enough edit distance."""
    if len(heard.replace(" ", "")) < MIN_TOKEN_LENGTH:
        return False
    if phonetic_key(heard.replace(" ", "")) != phonetic_key(term.replace(" ", "")):
        return False
    # Compare space-stripped: a split word ("cooper netties") differs from the
    # term only by the split, and counting that space as an edit is exactly
    # backwards — the split IS the mis-hearing we are trying to undo.
    bare_heard = heard.lower().replace(" ", "").replace("-", "")
    bare_term = term.lower().replace(" ", "").replace("-", "")

    # The distance budget scales with how discriminative the phonetic key is.
    #
    # A long identical key is already strong evidence: "kubernetes" and "cooper
    # netties" share the 6-symbol key `216532`, which almost nothing else does —
    # yet they are 6 edits apart, because a homophone can be spelled wildly
    # differently. Judging that by spelling distance alone rejects exactly the
    # case this exists for. Short keys are the opposite: 2–3 symbols collide
    # easily, so there the distance check is the only thing holding the line.
    key_length = len(phonetic_key(bare_term))
    ratio = max_ratio * (1.75 if key_length >= 5 else 1.0)
    budget = max(1, int(max(len(bare_term), len(bare_heard)) * ratio))
    return _distance(bare_heard, bare_term) <= budget


def correct(
    text: str,
    vocabulary,
    *,
    max_distance_ratio: float = DEFAULT_MAX_DISTANCE_RATIO,
) -> tuple[str, list[Correction]]:
    """Replace mis-heard vocabulary words in *text*. Pure.

    Returns the corrected text and what changed, so a caller can log the
    substitutions rather than silently rewriting what the user said.
    """
    terms = [t.strip() for t in vocabulary if t and t.strip()]
    if not text or not terms:
        return text, []

    # Longest first: a 2-token term must win over a 1-token one that also matches.
    terms.sort(key=lambda t: (-len(t.split()), -len(t)))
    # Case-folded on purpose. A token that differs from the vocabulary term ONLY
    # by case is not a mis-hearing — the recogniser produced the right word, and
    # case is a formatting preference. Rewriting it is actively harmful in the
    # place this feature matters most: "run yazses doctor" would become "run
    # YazSes doctor", which is not a command that exists. Found by running the
    # corrector over this repo's own docs, where it fired 891 times on the
    # lowercase command name.
    known = {t.lower() for t in terms}

    spans = [(m.start(), m.end(), m.group()) for m in _WORD_RE.finditer(text)]
    if not spans:
        return text, []

    corrections: list[Correction] = []
    out: list[str] = []
    cursor = 0        # index into `text`
    i = 0             # index into `spans`
    while i < len(spans):
        match_len, replacement = 0, ""
        # A token that is already a vocabulary word is correct — and must not be
        # swallowed into a wider window either. The docs write `yazses say`, and
        # a 2-token window happily read that as a mis-hearing of "YazSes",
        # deleting the subcommand. Checking only the *whole* window missed it.
        if _without_possessive(spans[i][2]).lower() in known:
            # Also covers the possessive: "YazSes's" is the right word with a
            # grammatical suffix, and correcting it to "YazSes" silently deletes
            # the "'s" and changes what the sentence means.
            i += 1
            continue
        for width in range(min(_MAX_PHRASE_TOKENS, len(spans) - i), 0, -1):
            # Only join tokens separated by a single plain space. Anything else —
            # punctuation, a quote, a newline — means these are not one spoken
            # word that the recogniser split, and joining across it produced
            # matches like `c "kubernetes`.
            if any(text[spans[i + k][1]:spans[i + k + 1][0]] != " " for k in range(width - 1)):
                continue
            if width > 1 and any(
                spans[i + k][2].lower() in _STOPWORDS for k in range(width)
            ):
                continue
            heard = text[spans[i][0]:spans[i + width - 1][1]]
            if heard.lower() in known:
                break                      # already correct — leave it alone
            hit = next((t for t in terms if _is_close(heard, t, max_distance_ratio)), None)
            if hit is not None:
                match_len, replacement = width, hit
                break
        if match_len:
            start, end = spans[i][0], spans[i + match_len - 1][1]
            out.append(text[cursor:start])
            out.append(replacement)
            corrections.append(Correction(text[start:end], replacement, start, end))
            cursor = end
            i += match_len
        else:
            i += 1
    out.append(text[cursor:])
    return "".join(out), corrections
