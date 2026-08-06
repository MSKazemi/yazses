"""Diacritize (ADR-v2-122) + SafeGlyph (ADR-v2-123) — pure cores."""
from __future__ import annotations

from yazses.diacritize.restore import restore_diacritics
from yazses.safeglyph.confusables import normalize_ascii, scan_confusables

# ---- diacritize -------------------------------------------------------------

def test_restore_words():
    assert restore_diacritics("a cafe cliche") == "a café cliché"
    assert restore_diacritics("jalapeno and pinata") == "jalapeño and piñata"
    assert restore_diacritics("") == ""


def test_case_preserved():
    assert restore_diacritics("Cafe") == "Café"
    assert restore_diacritics("CAFE") == "CAFÉ"
    assert restore_diacritics("Deja vu") == "Déjà vu"


def test_ambiguous_and_substrings_untouched():
    assert restore_diacritics("resume the expose") == "resume the expose"   # ambiguous → absent
    assert restore_diacritics("cafeteria") == "cafeteria"                   # whole words only


def test_phrases_and_extra_lexicon():
    assert restore_diacritics("creme brulee time") == "crème brûlée time"
    assert restore_diacritics("a tete-a-tete") == "a tête-à-tête"
    assert restore_diacritics("uber cool", extra={"uber": "über"}) == "über cool"


# ---- safeglyph --------------------------------------------------------------

def test_scan_homoglyph_and_mixed_script():
    findings = scan_confusables("pаypal")            # Cyrillic а inside a Latin word
    kinds = {f["kind"] for f in findings}
    assert "confusable" in kinds and "mixed-script" in kinds
    conf = next(f for f in findings if f["kind"] == "confusable")
    assert conf["index"] == 1 and conf["suggestion"] == "a"
    mixed = next(f for f in findings if f["kind"] == "mixed-script")
    assert mixed["suggestion"] == "paypal"
    greek = scan_confusables("tαxi")                 # Greek α inside a Latin word
    assert any(f["kind"] == "mixed-script" and f["suggestion"] == "taxi" for f in greek)


def test_scan_invisible_and_fullwidth():
    findings = scan_confusables("a​b")
    assert findings == [{"index": 1, "char": "​", "kind": "invisible", "suggestion": ""}]
    [f] = scan_confusables("Ａbc")                    # fullwidth Ａ
    assert f["kind"] == "confusable" and f["suggestion"] == "A"


def test_clean_text_no_findings():
    assert scan_confusables("hello world 123 !") == []
    assert scan_confusables("") == []
    assert scan_confusables("سلام") == []                 # non-Latin-only word is not mixed-script


def test_normalize_ascii():
    assert normalize_ascii("pаypаl") == "paypal"
    assert normalize_ascii("a​b­c") == "abc"
    assert normalize_ascii("ＨＩ") == "HI"
    assert normalize_ascii("plain") == "plain"


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "diacritize" in slugs and "safeglyph" in slugs
    assert Config().diacritize.enabled is False and Config().safeglyph.enabled is False
