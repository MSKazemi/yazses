"""Voice Snippets (ADR-v2-026) + Phonetic Corrector (ADR-v2-027) — pure layers."""
from __future__ import annotations

from yazses.postprocess.phonetic import correct_text, correct_word, phonetic_key
from yazses.snippets.expand import expand_snippet

ENTRIES = {"my signature": "Best,\nMohsen", "standup template": "Yesterday:\nToday:\nBlockers:"}


# ---- voice snippets --------------------------------------------------------

def test_expand_exact_trigger():
    assert expand_snippet("my signature", ENTRIES) == "Best,\nMohsen"


def test_expand_with_leading_verb():
    assert expand_snippet("insert my signature", ENTRIES) == "Best,\nMohsen"
    assert expand_snippet("expand standup template", ENTRIES).startswith("Yesterday")


def test_expand_no_match_returns_none():
    assert expand_snippet("some random dictation", ENTRIES) is None
    assert expand_snippet("", ENTRIES) is None


def test_expand_empty_store():
    assert expand_snippet("my signature", {}) is None


def test_expand_punctuation_insensitive():
    assert expand_snippet("Insert my signature.", ENTRIES) == "Best,\nMohsen"


# ---- phonetic corrector ----------------------------------------------------

def test_phonetic_key_folds_homophones():
    assert phonetic_key("kubernetes") == phonetic_key("cubernetties")


def test_phonetic_key_empty():
    assert phonetic_key("") == ""
    assert phonetic_key("123") == ""


def test_correct_word_fixes_mishearing():
    assert correct_word("cubernetties", ["Kubernetes", "Docker"]) == "Kubernetes"


def test_correct_word_leaves_exact_vocab():
    assert correct_word("Kubernetes", ["Kubernetes"]) == "Kubernetes"


def test_correct_word_skips_known_words():
    # 'three' is a known word → never rewritten toward vocab
    assert correct_word("three", ["Kubernetes"], known={"three"}) == "three"


def test_correct_word_leaves_far_tokens():
    assert correct_word("banana", ["Kubernetes"]) == "banana"


def test_correct_word_empty_token():
    assert correct_word("", ["Kubernetes"]) == ""


def test_correct_text_preserves_separators_and_case_of_replacement():
    out = correct_text("deploy to cubernetties now", ["Kubernetes"])
    assert out == "deploy to Kubernetes now"


def test_correct_text_empty_vocab_noop():
    assert correct_text("hello world", []) == "hello world"


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "snippets" in slugs and "phonetic" in slugs
    assert Config().snippets.enabled is False and Config().phonetic.enabled is False


def test_edit_distance_empty_args():
    from yazses.postprocess.phonetic import _edit_distance
    assert _edit_distance("", "abc") == 3
    assert _edit_distance("abc", "") == 3
    assert _edit_distance("abc", "abc") == 0


def test_correct_word_skips_vocab_term_with_empty_key():
    # a vocab entry that yields no phonetic key ("123") is skipped, real match still wins
    assert correct_word("cubernetties", ["123", "Kubernetes"]) == "Kubernetes"


def test_expand_bare_verb_matches_nothing():
    # phrase is exactly the verb → stripped to the verb, no trigger equals it → None
    assert expand_snippet("insert", ENTRIES) is None
