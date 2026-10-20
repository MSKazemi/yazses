"""The `[hotwords]` vocabulary, as input to guarded post-decode correction (pure).

`hotwords` was designed (ADR-v2-069) as a hotword trie plus an N-best rescorer. That
design has no producer: faster-whisper exposes no N-best list, and a second decode path
for it would risk the default one. The user-facing promise -- "add Kubernetes to your
vocabulary and it stops being mis-heard" -- is already kept by `vocab_correct` (#73),
which repairs mis-heard vocabulary words after decoding behind four guards (exact
phonetic key, small edit distance, no short tokens, a correct word is a fixed point).

So `[hotwords]` is now a second switch and a second source of terms for that one
corrector, and nothing else. This module only merges the sources; every decision about
*whether* to rewrite a word stays in `vocab_correct`, so there is exactly one guard to
tune and one false-alarm profile to measure.
"""

from __future__ import annotations

from collections.abc import Iterable


def merge_terms(base: Iterable[str], extra: Iterable[str]) -> list[str]:
    """`base` followed by the `extra` terms it does not already contain. Pure.

    Case-insensitive de-duplication that keeps the first spelling seen, so the personal
    dictionary's capitalisation wins over a config entry for the same word. Blank and
    non-string entries are dropped rather than raised on: a hand-edited config must not
    be able to stop dictation.
    """
    out: list[str] = []
    seen: set[str] = set()
    for term in (*base, *extra):
        if not isinstance(term, str):
            continue
        t = term.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out
