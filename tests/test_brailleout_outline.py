"""BrailleOut (ADR-v2-117) + Spoken Outline (ADR-v2-124) — pure cores."""
from __future__ import annotations

from yazses.brailleout.ueb import to_braille
from yazses.outline.tree import OutlineItem, apply_outline_op, new_outline, render


# ---- brailleout -------------------------------------------------------------

def test_grade1_letters():
    assert to_braille("hello", grade=1) == "⠓⠑⠇⠇⠕"
    assert to_braille("", grade=1) == ""


def test_capital_indicator():
    assert to_braille("Hello", grade=1) == "⠠⠓⠑⠇⠇⠕"


def test_digits_get_one_number_sign():
    assert to_braille("42", grade=1) == "⠼⠙⠃"
    assert to_braille("a1b", grade=1) == "⠁⠼⠁⠃"


def test_grade2_wordsign_vs_grade1():
    assert to_braille("and") == "⠯"                       # standalone wordsign
    assert to_braille("and", grade=1) == "⠁⠝⠙"
    assert to_braille("the cat") == "⠮ ⠉⠁⠞"


def test_grade2_groupsign_within_word():
    assert to_braille("wish") == "⠺⠊⠩"                    # sh groupsign
    assert to_braille("going") == "⠛⠕⠬"                   # ing groupsign
    assert to_braille("standalone").startswith("⠌")       # st groupsign


def test_punctuation_and_passthrough():
    assert to_braille("hi.") == "⠓⠊⠲"
    assert to_braille("café")[-1] == "é"                  # unknown char passes through


# ---- outline ----------------------------------------------------------------

def test_add_and_cursor():
    s = new_outline()
    s = apply_outline_op(s, "add", "groceries")
    s = apply_outline_op(s, "add", "hardware")
    assert [i.text for i in s["items"]] == ["groceries", "hardware"]
    assert s["cursor"] == 1


def test_indent_clamped_and_promote():
    s = new_outline()
    s = apply_outline_op(s, "add", "a")
    s = apply_outline_op(s, "indent")                     # first item can't indent
    assert s["items"][0].level == 0
    s = apply_outline_op(s, "add", "b")
    s = apply_outline_op(s, "indent")
    s = apply_outline_op(s, "indent")                     # capped at parent+1
    assert s["items"][1].level == 1
    s = apply_outline_op(s, "promote")
    assert s["items"][1].level == 0
    s = apply_outline_op(s, "promote")                    # floor 0
    assert s["items"][1].level == 0


def test_unknown_op_and_empty_are_noops():
    s = new_outline()
    assert apply_outline_op(s, "frobnicate") == s
    assert apply_outline_op(s, "indent") == s             # no cursor yet
    assert render(s) == ""


def test_render_markdown_and_collapse():
    s = new_outline()
    for op, text in [("add", "a"), ("add", "b"), ("indent", ""), ("add", "c"), ("add", "d"), ("promote", "")]:
        s = apply_outline_op(s, op, text)
    assert render(s) == "- a\n  - b\n  - c\n- d"
    s2 = apply_outline_op({"items": s["items"], "cursor": 0}, "collapse")
    assert render(s2) == "- a\n- d"                       # collapsed subtree hidden
    s3 = apply_outline_op(s2, "expand")
    assert render(s3) == render(s)


def test_render_opml_nesting_and_escape():
    s = new_outline()
    for op, text in [("add", "a & b"), ("add", "child"), ("indent", "")]:
        s = apply_outline_op(s, op, text)
    out = render(s, fmt="opml")
    assert out.startswith('<opml version="2.0"><body>')
    assert '<outline text="a &amp; b"><outline text="child"></outline></outline>' in out
    s = apply_outline_op(apply_outline_op(s, "promote"), "add", "sibling")
    out2 = render(s, fmt="opml")                          # sibling closes the previous element
    assert '<outline text="child"></outline><outline text="sibling"></outline>' in out2


def test_cursor_moves():
    s = new_outline()
    s = apply_outline_op(s, "add", "a")
    s = apply_outline_op(s, "add", "b")
    s = apply_outline_op(s, "up")
    assert s["cursor"] == 0
    s = apply_outline_op(s, "up")                         # clamped
    assert s["cursor"] == 0
    s = apply_outline_op(s, "down")
    assert s["cursor"] == 1
    assert s["items"][0] == OutlineItem("a", 0, False)


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "brailleout" in slugs and "outline" in slugs
    assert Config().brailleout.enabled is False and Config().outline.enabled is False
    assert Config().brailleout.grade == 2 and Config().outline.format == "markdown"
