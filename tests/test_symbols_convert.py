"""Emoji & Symbol by Voice (ADR-v2-055) + Voice Unit Conversion (ADR-v2-056) — pure cores."""
from __future__ import annotations

from yazses.convert.units import apply_conversions
from yazses.symbols.lookup import apply_symbols


# ---- symbols ---------------------------------------------------------------

def test_apply_symbols_basic():
    assert apply_symbols("turn right arrow here") == "turn → here"
    assert apply_symbols("add a degree sign") == "add a °"


def test_apply_symbols_longest_phrase_wins():
    # "thumbs up emoji" must beat "thumbs up"
    assert apply_symbols("thumbs up emoji") == "👍"


def test_apply_symbols_case_insensitive():
    assert apply_symbols("Check Mark") == "✓"


def test_apply_symbols_leaves_plain_text():
    assert apply_symbols("nothing to replace") == "nothing to replace"
    assert apply_symbols("") == ""


# ---- unit conversion -------------------------------------------------------

def test_convert_length_number_word():
    assert apply_conversions("twenty miles in kilometers") == "32.19 kilometers"


def test_convert_length_digits():
    assert apply_conversions("3 feet to inches") == "36 inches"


def test_convert_temperature():
    assert apply_conversions("100 celsius to fahrenheit") == "212 fahrenheit"
    assert apply_conversions("32 fahrenheit to celsius") == "0 celsius"


def test_convert_volume():
    assert apply_conversions("2 cups to milliliters") == "473.18 milliliters"


def test_convert_incompatible_dimensions_untouched():
    assert apply_conversions("5 miles to kilograms") == "5 miles to kilograms"


def test_convert_to_kelvin():
    assert apply_conversions("0 celsius to kelvin") == "273.15 kelvin"


def test_convert_non_number_value_in_matching_span_untouched():
    # regex matches (word unit to unit) but the value word isn't a number → left alone
    assert apply_conversions("many miles to kilometers") == "many miles to kilometers"


def test_convert_non_number_untouched():
    assert apply_conversions("cats to dogs") == "cats to dogs"
    assert apply_conversions("") == ""


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "symbols" in slugs and "convert" in slugs
    assert Config().commands.symbols is False and Config().convert.enabled is False
