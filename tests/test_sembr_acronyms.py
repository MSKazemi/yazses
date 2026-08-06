"""Semantic Line Breaks (ADR-v2-111) + Acronym/Glossary Manager (ADR-v2-114) — pure cores."""
from __future__ import annotations

from yazses.acronyms.glossary import AcronymState
from yazses.sembr.breaks import semantic_breaks

# ---- semantic line breaks --------------------------------------------------

def test_semantic_breaks_sentences_and_clauses():
    text = "Hello world. This is fine, but that is broken; really."
    out = semantic_breaks(text)
    assert out == "Hello world.\nThis is fine,\nbut that is broken;\nreally."


def test_semantic_breaks_empty_and_whitespace():
    assert semantic_breaks("") == ""
    assert semantic_breaks("   ") == ""
    assert semantic_breaks("no breaks here") == "no breaks here"


def test_semantic_breaks_soft_wrap():
    out = semantic_breaks("aaaa bbbb cccc dddd", max_len=10)
    assert all(len(line) <= 10 for line in out.split("\n"))
    # a single token longer than max_len can't be split → stays whole
    assert semantic_breaks("supercalifragilistic", max_len=5) == "supercalifragilistic"


# ---- acronym / glossary manager --------------------------------------------

def test_acronym_expand_first_use_then_contract():
    s = AcronymState()
    s.define("WHO", "World Health Organization")
    assert s.resolve("WHO") == "World Health Organization (WHO)"   # first use expands
    assert s.resolve("W-H-O") == "WHO"                             # later contracts (key-normalized)
    assert s.resolve("unknown") == "unknown"                       # pass-through


def test_acronym_observe_marks_expanded():
    s = AcronymState()
    s.observe("The World Health Organization (WHO) said so.")
    assert s.resolve("WHO") == "WHO"                               # already written out → contract
    assert s._defs["WHO"] == "World Health Organization"


def test_acronym_audit():
    s = AcronymState()
    doc = "The FBI and the CIA met. Federal Bureau of Investigation (FBI) leads."
    warnings = s.audit(doc)
    assert any("CIA" in w for w in warnings)      # used, never defined
    assert not any("FBI" in w for w in warnings)  # defined in-doc


def test_acronym_paren_without_valid_expansion():
    # "(XYZ)" with no preceding words whose initials match → not treated as a definition
    s = AcronymState()
    s.observe("the quick brown fox (XYZ) jumped")
    assert "XYZ" not in s._defs
    assert any("XYZ" in w for w in s.audit("the quick brown fox (XYZ) jumped"))


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "sembr" in slugs and "acronyms" in slugs
    assert Config().sembr.enabled is False and Config().acronyms.enabled is False
