"""Personal-vocabulary recovery after decoding (#73).

The acceptance criteria are two-sided and the second one is the hard one: vocab
words must be recovered *and* vocab-free speech must come through untouched.
Rewriting a transcript the user cannot see is worse than the mis-hearing it
fixes, so the no-damage direction gets the most tests here.
"""

from __future__ import annotations

import pytest

from yazses.postprocess.vocab_correct import correct, phonetic_key

VOCAB = ["Kubernetes", "YazSes", "PostgreSQL", "Ardebili", "faster-whisper", "kubectl"]


def _fix(text, vocab=VOCAB):
    return correct(text, vocab)[0]


# ---- the phonetic key ------------------------------------------------------


def test_key_collapses_the_swaps_a_recogniser_actually_makes():
    assert phonetic_key("kubernetes") == phonetic_key("cooper netties".replace(" ", ""))
    assert phonetic_key("phone") == phonetic_key("fone")


def test_key_separates_genuinely_different_words():
    assert phonetic_key("cat") != phonetic_key("dog")
    assert phonetic_key("dictation") != phonetic_key("kubernetes")


def test_key_is_stable_under_case():
    assert phonetic_key("YazSes") == phonetic_key("yazses")


def test_key_of_a_non_word_is_empty_not_a_crash():
    assert phonetic_key("") == ""
    assert phonetic_key("123") == ""


# ---- recovering vocabulary (acceptance 1) ----------------------------------


def test_single_word_mishearing_is_recovered():
    assert _fix("deploy it to cubernetties today") == "deploy it to Kubernetes today"


def test_multi_word_mishearing_is_reassembled():
    """The interesting case: the recogniser split one word into two."""
    assert _fix("run it on cooper netties") == "run it on Kubernetes"


def test_the_product_name_is_recovered():
    assert _fix("I use yaz says every day") == "I use YazSes every day"


def test_a_surname_is_recovered():
    assert _fix("written by ardebilly") == "written by Ardebili"


def test_correction_reports_what_it_changed():
    _, changes = correct("deploy to cubernetties", VOCAB)
    assert len(changes) == 1
    assert (changes[0].heard, changes[0].corrected) == ("cubernetties", "Kubernetes")


def test_a_case_only_difference_is_left_alone():
    """Not a mis-hearing — and rewriting it breaks commands.

    "run yazses doctor" must not become "run YazSes doctor": that is not a
    command that exists. Case is formatting, not recognition.
    """
    assert _fix("we use postgresql here") == "we use postgresql here"
    assert _fix("run yazses doctor now") == "run yazses doctor now"


# ---- causing no damage (acceptance 2 — the one that matters) ----------------


def test_vocab_free_speech_is_untouched():
    text = "the quick brown fox jumps over the lazy dog near the river bank"
    assert _fix(text) == text


def test_ordinary_words_that_merely_rhyme_are_not_replaced():
    """Distance guard: the key is lossy, so this is what stops a false hit."""
    for sentence in ["the cat sat on the mat", "please send the report", "an open door"]:
        assert _fix(sentence) == sentence


def test_short_tokens_are_never_corrected():
    """Below four characters the key space is too crowded to be safe."""
    assert _fix("an ox is by the sea") == "an ox is by the sea"


def test_a_correct_transcript_is_a_fixed_point():
    text = "deploy Kubernetes with kubectl and PostgreSQL"
    assert _fix(text) == text
    assert _fix(_fix(text)) == text, "running twice must not drift"


def test_empty_inputs_are_safe():
    assert correct("", VOCAB) == ("", [])
    assert correct("some text", []) == ("some text", [])
    assert correct("some text", ["", "   "]) == ("some text", [])


def test_punctuation_and_spacing_are_preserved():
    assert _fix("deploy cubernetties, then stop.") == "deploy Kubernetes, then stop."


def test_only_whole_words_are_matched():
    """A vocab word inside a longer word must not trigger a rewrite."""
    text = "unkubernetesish is not a word"
    assert _fix(text) == text


# ---- knobs -----------------------------------------------------------------


def test_a_stricter_ratio_rejects_a_looser_match():
    loose = correct("deploy to cubernetties", VOCAB, max_distance_ratio=0.4)[0]
    strict = correct("deploy to cubernetties", VOCAB, max_distance_ratio=0.01)[0]
    assert "Kubernetes" in loose
    assert strict == "deploy to cubernetties"


@pytest.mark.parametrize("term", VOCAB)
def test_every_vocabulary_term_survives_a_round_trip(term):
    """A term spoken correctly must never be rewritten into a different term."""
    assert _fix(f"the word {term} appears here") == f"the word {term} appears here"


# ---- adversarial: real prose must survive untouched ------------------------


def test_a_real_english_corpus_is_not_rewritten():
    """The relaxed distance budget must not cost false positives on real prose.

    Method matters here: the vocabulary is a set of realistic technical terms
    that do **not** occur anywhere in this repository's documentation, so any
    change at all is definitionally a false positive. (Using the project's own
    vocabulary would be unsound — the docs deliberately contain "yaz says" and
    "Cuber Netties" as worked examples of these very mis-hearings, and correcting
    those is the feature working.)
    """
    from pathlib import Path

    docs = Path(__file__).resolve().parent.parent / "docs"
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in sorted(docs.glob("*.md"))[:12])
    assert len(corpus) > 20_000, "corpus too small to be evidence"

    absent_vocab = [
        "Grafana", "Terraform", "Prometheus", "Kagglehub",
        "Zsolnay", "Bialetti", "Nakagawa", "Oberhausen",
    ]
    for term in absent_vocab:
        assert term.lower() not in corpus.lower(), f"{term} occurs — not a clean control"

    fixed, changes = correct(corpus, absent_vocab)
    assert changes == [], f"false positives on ordinary prose: {changes[:5]}"
    assert fixed == corpus


def test_a_possessive_keeps_its_suffix():
    """Correcting "YazSes\u2019s" to "YazSes" deletes the \u2019s and changes the meaning."""
    assert _fix("YazSes's daemon") == "YazSes's daemon"
    assert _fix("Kubernetes's scheduler") == "Kubernetes's scheduler"
