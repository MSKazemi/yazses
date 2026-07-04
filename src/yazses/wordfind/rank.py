"""Reverse-dictionary candidate ranking (pure) — ADR-v2-118.

Rank lexicon words by content-word overlap between the spoken description and each definition.
Pure and deterministic; the built-in lexicon is a small demo tier — users extend it, and
WordNet/embedding backends are optional extras.
"""
from __future__ import annotations

import re

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is",
    "it", "its", "of", "on", "or", "that", "the", "them", "they", "this", "to", "was",
    "what", "when", "where", "which", "who", "with", "you", "your", "word", "words",
    "something", "thing", "someone", "means", "meaning", "called", "describes",
}
_LEXICON = {
    "evaporation": "the process by which liquid water turns into gas or vapor",
    "condensation": "gas or vapor cooling back into liquid water drops",
    "precipitation": "rain snow sleet or hail falling from clouds to the ground",
    "serendipity": "finding something good or valuable by happy accident or luck",
    "procrastinate": "to keep delaying or putting off a task you should do now",
    "nostalgia": "a sentimental longing for the past or for happy old memories",
    "insomnia": "the persistent inability to fall asleep or stay asleep at night",
    "petrichor": "the pleasant earthy smell after rain falls on dry ground",
    "ambidextrous": "able to use both the right and left hand equally well",
    "hypotenuse": "the longest side of a right triangle opposite the right angle",
    "photosynthesis": "how plants turn sunlight water and carbon dioxide into food",
    "echolocation": "locating objects by reflected sound as bats and dolphins do",
    "hibernation": "a deep winter sleep in which animals slow their body functions",
    "metamorphosis": "the transformation of an animal changing form as caterpillar to butterfly",
    "palindrome": "a word or phrase that reads the same backward as forward",
    "onomatopoeia": "a word that imitates the sound it names like buzz or hiss",
    "eclipse": "when one body in space blocks the light of the sun or moon",
    "mirage": "an optical illusion of water caused by hot air over a road or desert",
    "vertigo": "a spinning dizzy sensation of losing balance often from heights",
    "quarantine": "a period of isolation to stop a disease from spreading",
}


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower())
            if w not in _STOPWORDS and len(w) > 2}


def rank_candidates(query: str, lexicon: dict[str, str] | None = None,
                    limit: int = 5) -> list[tuple[str, float]]:
    """Rank reverse-dictionary candidates for a spoken description. Pure.

    Score = content-word overlap with each definition, normalized by query size; deterministic
    ties break alphabetically. ``lexicon`` merges user entries over the built-in demo tier.
    """
    words = _content_words(query)
    if not words:
        return []
    merged = {**_LEXICON, **(lexicon or {})}
    scored = []
    for candidate, definition in merged.items():
        overlap = words & _content_words(definition)
        if overlap:
            scored.append((candidate, round(len(overlap) / len(words), 3)))
    scored.sort(key=lambda ws: (-ws[1], ws[0]))
    return scored[:max(limit, 0)]
