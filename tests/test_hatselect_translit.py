"""HatSelect (ADR-v2-115) + Transliteration (ADR-v2-116) — pure cores."""
from __future__ import annotations

from yazses.hatselect.labels import (
    Selection,
    TokenRef,
    assign_labels,
    plan_structural_edit,
    resolve_reference,
)
from yazses.translit.scheme import detect_scheme, transliterate

# ---- hatselect -------------------------------------------------------------

def test_assign_labels():
    labels = assign_labels(["def", "foo", "(", "x", ")"])
    assert labels["alpha"] == TokenRef(0, "def")
    assert labels["charlie"] == TokenRef(2, "(")
    assert len(assign_labels(["t"] * 40)) == 26      # capped at the NATO alphabet


def test_resolve_reference():
    labels = assign_labels(["a", "b", "c", "d", "e"])
    assert resolve_reference("select alpha to charlie", labels) == Selection(0, 2)
    assert resolve_reference("delete bravo", labels) == Selection(1, 1)
    assert resolve_reference("take charlie to alpha", labels) == Selection(0, 2)   # order-independent
    assert resolve_reference("nothing here", labels) is None


def test_plan_structural_edit():
    sel = Selection(1, 3)
    assert plan_structural_edit("delete", sel) == [{"op": "delete", "start": 1, "end": 3}]
    assert plan_structural_edit("take", sel) == [{"op": "select", "start": 1, "end": 3}]
    assert plan_structural_edit("wrap it", sel) == [{"op": "wrap", "start": 1, "end": 3}]
    assert plan_structural_edit("frobnicate", sel) == []       # unknown verb
    assert plan_structural_edit("delete", None) == []


# ---- transliteration -------------------------------------------------------

def test_transliterate_finglish():
    assert transliterate("salam") == "سالام"
    assert transliterate("khoob") == "خوب"                     # kh + oo + b
    assert transliterate("Hello!") .endswith("!")              # punctuation preserved
    assert transliterate("abc", "unknown_scheme") == "abc"     # unknown scheme → passthrough


def test_transliterate_longest_match_and_nonalpha():
    # 'sh' maps to a single letter (longest-match), not s + h
    assert transliterate("sh") == "ش"
    assert transliterate("a b") == "ا ب"                       # spaces preserved
    assert transliterate("ñ") == "ñ"                           # alpha char absent from table → as-is


def test_detect_scheme():
    assert detect_scheme("salam chetori", "finglish") == "finglish"
    assert detect_scheme("سلام") is None                       # non-ASCII → no transliteration
    assert detect_scheme("") is None
    assert detect_scheme("123 !!!") is None                    # no letters


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "hatselect" in slugs and "translit" in slugs
    assert Config().hatselect.enabled is False and Config().translit.enabled is False
