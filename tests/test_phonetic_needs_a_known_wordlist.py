"""Phonetic correction cannot be made safe by tuning; it needs a word list.

A personal lexicon naturally contains ordinary English words — a user who dictates about
version control adds "Git", one who dictates prose adds "head". A token that merely
*sounds* like one is then rewritten to it. Against a real 24-entry vocabulary, six of
eleven ordinary sentences were corrupted:

    "get the file"          ->  "Git the file"
    "go ahead and try it"   ->  "go head and try it"
    "I get it now"          ->  "I Git it now"
    "we had a great time"   ->  "we head a Git time"

## Why this file exists rather than a fix

The obvious remedy is to tighten `max_distance`. It cannot work, and this test is here to
stop anyone spending an afternoon discovering that:

    get    -> Git      0.000     must NOT be corrected
    had    -> head     0.000     must NOT be corrected
    githab -> GitHub   0.000     MUST be corrected

"get" and "Git" are phonetic twins. The damage and the legitimate corrections sit at the
*same* score, so no threshold, minimum length, or scoring tweak separates them. Only a set
of correctly-spelled words does — which is precisely what `correct_word`'s `known`
parameter is for, and `core/daemon.py` calls `correct_text(text, _vocab)` without it.

Choosing that word list is a data decision — which list, how large, what licence — so it
is left open rather than guessed at. What is pinned here is the measurement, so the
conclusion does not have to be rediscovered.

`[phonetic] enabled` is off by default, so this reaches whoever turns it on.
"""

from __future__ import annotations

import pytest

from yazses.postprocess.phonetic import _edit_distance, correct_text, phonetic_key

VOCAB = ["Git", "GitHub", "head", "YazSes", "Mohsen", "Bologna"]


def _score(token: str, term: str) -> float:
    a, b = phonetic_key(token.lower()), phonetic_key(str(term))
    denom = max(len(a), len(b))
    return _edit_distance(a, b) / denom if denom else 1.0


@pytest.mark.parametrize(
    "token,term",
    [("get", "Git"), ("had", "head")],
)
def test_a_real_word_can_be_a_phonetic_twin_of_a_lexicon_entry(token, term) -> None:
    """The premise: these are indistinguishable by sound, not merely close."""
    assert _score(token, term) == 0.0


@pytest.mark.parametrize("token,term", [("githab", "GitHub"), ("yazsis", "YazSes")])
def test_a_real_misrecognition_scores_the_same(token, term) -> None:
    """And so no threshold can tell the two apart."""
    assert _score(token, term) == 0.0


def test_no_threshold_separates_them() -> None:
    """Stated as the property, so 'just lower max_distance' fails here rather than later."""
    damage = _score("get", "Git")
    wanted = _score("githab", "GitHub")
    assert damage == wanted, (
        "the scores no longer collide — if a threshold now separates them, revisit the "
        "module warning and this file"
    )


def test_the_known_parameter_is_the_remedy() -> None:
    """It already exists and already works; nothing passes it."""
    assert correct_text("get the file", VOCAB) == "Git the file"
    assert correct_text("get the file", VOCAB, known={"get", "the", "file"}) == (
        "get the file"
    )


def test_the_daemon_still_does_not_pass_it() -> None:
    """Fails the day someone wires a word list, which is the point.

    When that happens this file should be revisited: the warning in `phonetic.py` and the
    measurement above stop being the whole story.
    """
    import inspect

    from yazses.core import daemon

    source = inspect.getsource(daemon)
    assert "correct_text(text, _vocab)" in source, (
        "the phonetic call site changed — if `known` is now passed, update this test and "
        "the warning in postprocess/phonetic.py"
    )


def test_real_corrections_still_happen_when_the_feature_is_used_as_intended() -> None:
    """Not a broken feature — a feature that needs its guard wired."""
    assert correct_text("githab", VOCAB) == "GitHub"
    assert correct_text("yazsis", VOCAB) == "YazSes"


def test_an_exact_vocabulary_spelling_is_never_rewritten() -> None:
    """The one guard that IS wired, pinned so it is not lost in a later fix."""
    assert correct_text("Git", VOCAB) == "Git"
    assert correct_text("GitHub", VOCAB) == "GitHub"
