"""Language-ID routing for code-switch transcription (pure scaffolding).

Parse the configured pair, pick a span's dominant language, and detect whether an
utterance code-switches *within the configured pair*. The CS-adapted model that
actually transcribes both languages is trained out-of-band and gated; this is the
routing layer that decides when to use it.
"""
from __future__ import annotations

import re

_PAIR_RE = re.compile(r"^([a-z]{2})-([a-z]{2})$")


def parse_pair(spec: str) -> tuple[str, str]:
    """Parse a ``"xx-yy"`` language pair into ``(xx, yy)``; raise on anything else."""
    m = _PAIR_RE.match(spec or "")
    if not m:
        raise ValueError(f"invalid language pair {spec!r}; expected e.g. 'fa-en'")
    return m.group(1), m.group(2)


def dominant_language(lang_probs: dict[str, float]) -> str | None:
    """Return the highest-probability language id, or None for an empty mapping."""
    if not lang_probs:
        return None
    return max(lang_probs, key=lambda lang: lang_probs[lang])


def is_code_switched(span_languages, pair: tuple[str, str]) -> bool:
    """True if the spans use *both* languages of the configured pair.

    Languages outside the pair are ignored (not a code-switch event for this pair).
    """
    present = {lang for lang in span_languages if lang in pair}
    return len(present) >= 2
