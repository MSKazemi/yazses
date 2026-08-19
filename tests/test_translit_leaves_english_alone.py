"""With `[translit]` enabled, every English sentence was transliterated into Persian.

`detect_scheme`'s docstring promised *"so English passes through"*, and the code returned
the scheme for **any** all-ASCII text — which is every English sentence ever dictated. The
caller transliterates whenever it is truthy, so:

    "hello how are you"        ->  "ههللو هوو اره یو"
    "send me the file please"  ->  "سهند مه تهه فیله پلهاسه"
    "the quick brown fox"      ->  "تهه قویcک بروون فوx"

The gate never gated. Enabling the feature did not degrade English dictation, it destroyed
it — and the stray Latin `c` and `x` in the last one show the output is not even
well-formed Persian.

`[translit] enabled` is off by default, so this reached whoever turned it on. For a
Persian-speaking user that is the intended path, which is what makes it worth fixing
rather than documenting.

## The trade-off, stated because it is real

Detection uses a short list of very common English words. A Finglish sentence whose
romanization collides with one — "to khoobi?", where Persian *to* means "you" — is left in
Latin script.

That is the right direction, and the same asymmetry used for the ITN, self-repair and
compute guards: a missed transliteration leaves readable text the user can retry; a false
one replaces the sentence with nonsense they cannot read back.

The marker list is purpose-built rather than borrowed. `analysis._VOCAB_STOPWORDS` exists
and looks like a fit, but it is missing "is", "it", "to", "a" and "me" — exactly the words
that decide this question — because it was built to filter vocabulary proposals. Reusing
it would have been the "one list, two jobs" mistake this repo keeps hitting.
"""

from __future__ import annotations

import pytest

from yazses.translit.scheme import detect_scheme, looks_like_english, transliterate


def _through_daemon(text: str) -> str:
    """Exactly what `core/daemon.py` does when [translit] is enabled."""
    scheme = detect_scheme(text, "finglish")
    return transliterate(text, scheme) if scheme else text


ENGLISH = [
    "hello how are you",
    "send me the file please",
    "the quick brown fox",
    "I am fine thank you",
    "it is done",
    "can you check this",
    "there is no problem with that",
]

FINGLISH = ["salam chetori", "man khoobam", "khoda hafez", "merci"]


@pytest.mark.parametrize("text", ENGLISH)
def test_english_is_left_exactly_as_dictated(text: str) -> None:
    assert _through_daemon(text) == text, "an English sentence was transliterated"


@pytest.mark.parametrize("text", FINGLISH)
def test_finglish_is_still_transliterated(text: str) -> None:
    """A gate that refused everything would pass every test above and kill the feature."""
    out = _through_daemon(text)
    assert out != text
    assert any(ord(c) > 0x600 for c in out), f"not Persian script: {out!r}"


def test_non_ascii_input_is_refused_as_before() -> None:
    """The pre-existing check: already-Persian text is not re-transliterated."""
    assert detect_scheme("سلام چطوری", "finglish") is None


def test_empty_and_symbol_only_input() -> None:
    assert detect_scheme("", "finglish") is None
    assert detect_scheme("123 !?", "finglish") is None


def test_the_collision_case_errs_toward_leaving_it_alone() -> None:
    """Documented, not accidental: Persian "to" is English "to".

    The sentence stays in Latin script. Recorded as a test so the behaviour is a decision
    rather than a surprise, and so anyone tempted to lengthen the marker list sees the
    cost first.
    """
    assert looks_like_english("to khoobi")
    assert _through_daemon("to khoobi") == "to khoobi"


def test_the_marker_list_is_not_the_vocabulary_stopword_list() -> None:
    """They look interchangeable and are not.

    `_VOCAB_STOPWORDS` is missing the words that decide this question, so borrowing it
    would have left half the English sentences being mangled.
    """
    from yazses.learning.analysis import _VOCAB_STOPWORDS

    deciders = {"is", "it", "to", "a", "me"}
    assert not (deciders & _VOCAB_STOPWORDS), (
        "the vocabulary stopword list now covers these — re-check whether one list can "
        "serve both jobs before merging them"
    )
    assert deciders <= {w for w in "is it to a me".split() if looks_like_english(w)}
