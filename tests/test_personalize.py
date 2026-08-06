"""Voiceprint Mind P1 — biasing prompt builder (design/v2-cognitive-layer §3.1).

Compose Whisper's ``initial_prompt`` from the user vocabulary + frequent personal
terms mined from the corpus, so the recognizer spells the user's jargon/proper nouns.
Pure, no training, no model — fully testable.
"""
from __future__ import annotations

from yazses.personalize.prompt_builder import (
    build_prompt,
    mine_ngrams,
    mine_personal,
    mine_terms,
)

# ---- build_prompt ----------------------------------------------------------

def test_build_prompt_unions_vocab_and_mined_terms():
    out = build_prompt(["Kubernetes", "kubectl"], ["GitHub"], existing_prompt="")
    for term in ("Kubernetes", "kubectl", "GitHub"):
        assert term in out


def test_build_prompt_preserves_existing_prompt():
    out = build_prompt(["Redis"], [], existing_prompt="Meeting notes.")
    assert "Meeting notes." in out
    assert "Redis" in out


def test_build_prompt_dedupes_case_insensitively():
    out = build_prompt(["GitHub", "github"], ["GitHub"], existing_prompt="")
    assert out.lower().count("github") == 1


def test_build_prompt_caps_term_count():
    terms = [f"Term{i}" for i in range(200)]
    out = build_prompt(terms, [], existing_prompt="", max_terms=10)
    assert sum(out.count(f"Term{i}") for i in range(200)) == 10


def test_build_prompt_empty_inputs_returns_existing():
    assert build_prompt([], [], existing_prompt="hello") == "hello"
    assert build_prompt([], [], existing_prompt="") == ""


# ---- mine_terms ------------------------------------------------------------

def test_mine_terms_returns_frequent_content_words():
    texts = [
        "deploy the kubernetes pod",
        "the kubernetes cluster is down",
        "restart kubernetes now",
    ]
    mined = mine_terms(texts, top_k=5, min_count=2)
    assert "kubernetes" in mined
    assert "the" not in mined  # stopword filtered


def test_mine_terms_ignores_rare_words():
    texts = ["a unique word here", "common common common"]
    mined = mine_terms(texts, top_k=5, min_count=2)
    assert "unique" not in mined
    assert "common" in mined


def test_mine_terms_empty_is_safe():
    assert mine_terms([], top_k=5) == []


# ---- mine_ngrams (Personal Adapter P1) -------------------------------------

def test_mine_ngrams_finds_frequent_content_phrase():
    texts = ["faster whisper is fast", "i love faster whisper", "faster whisper rocks"]
    grams = mine_ngrams(texts, n=2, min_count=2)
    assert "faster whisper" in grams


def test_mine_ngrams_drops_function_word_runs():
    texts = ["it is on the table", "put it on the shelf", "on the roof it is"]
    grams = mine_ngrams(texts, n=2, min_count=2)
    # "on the" is all-stopword -> never counted
    assert "on the" not in grams


def test_mine_ngrams_respects_min_count_and_n_lt_2():
    assert mine_ngrams(["unique phrase here"], n=2, min_count=2) == []
    assert mine_ngrams(["anything at all"], n=1) == []


def test_mine_ngrams_trigrams():
    texts = ["voice print mind works", "the voice print mind again", "voice print mind yes"]
    grams = mine_ngrams(texts, n=3, min_count=2)
    assert "voice print mind" in grams


# ---- mine_personal (combined) ----------------------------------------------

def test_mine_personal_phrases_precede_unigrams():
    texts = ["faster whisper model", "faster whisper model", "faster whisper model"]
    out = mine_personal(texts, max_terms=10, min_count=2)
    # a multi-word phrase should appear, ahead of any bare unigram
    assert any(" " in t for t in out)
    first_phrase = next(i for i, t in enumerate(out) if " " in t)
    first_unigram = next((i for i, t in enumerate(out) if " " not in t), len(out))
    assert first_phrase < first_unigram


def test_mine_personal_caps_and_dedupes():
    texts = ["alpha beta gamma"] * 3
    out = mine_personal(texts, max_terms=4, min_count=2)
    assert len(out) <= 4
    assert len(out) == len(set(out))


def test_mine_personal_empty_is_safe():
    assert mine_personal([], max_terms=5) == []
