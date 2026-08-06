"""Spoken Code Mode (ADR-v2-031) + Spoken Math→LaTeX (ADR-v2-032) — pure grammars."""
from __future__ import annotations

from yazses.code.spoken import spoken_symbols, to_case
from yazses.math.latex import spoken_to_latex

# ---- spoken code: symbols --------------------------------------------------

def test_symbols_basic():
    assert spoken_symbols("x equals open paren a plus b close paren") == "x = ( a + b )"


def test_symbols_longest_match_wins():
    assert spoken_symbols("a less than or equal b") == "a <= b"
    assert spoken_symbols("a arrow b") == "a -> b"


def test_symbols_case_insensitive():
    assert spoken_symbols("Open Brace") == "{"


def test_symbols_leave_plain_words():
    assert spoken_symbols("just talking normally") == "just talking normally"


# ---- spoken code: casing ---------------------------------------------------

def test_to_case_styles():
    words = ["user", "id"]
    assert to_case(words, "snake") == "user_id"
    assert to_case(words, "camel") == "userId"
    assert to_case(words, "pascal") == "UserId"
    assert to_case(words, "constant") == "USER_ID"
    assert to_case(words, "kebab") == "user-id"


def test_to_case_unknown_style_joins_spaces():
    assert to_case(["a", "b"], "weird") == "a b"


def test_to_case_empty():
    assert to_case([], "snake") == ""
    assert to_case(["", "  "], "snake") == ""


# ---- spoken math -----------------------------------------------------------

def test_math_squared_and_plus():
    assert spoken_to_latex("x squared plus y squared") == "x^{2} + y^{2}"


def test_math_square_root():
    assert spoken_to_latex("square root of x") == r"\sqrt{x}"


def test_math_greek_and_symbols():
    assert spoken_to_latex("alpha plus beta") == r"\alpha + \beta"
    assert spoken_to_latex("integral of infinity") == r"\int of \infty"


def test_math_to_the_power():
    assert spoken_to_latex("e to the x") == "e^{x}"


def test_math_cubed():
    assert spoken_to_latex("x cubed") == "x^{3}"


def test_math_empty():
    assert spoken_to_latex("") == ""


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "code" in slugs and "math" in slugs
    assert Config().code.enabled is False and Config().math.enabled is False
