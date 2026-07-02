"""Spoken unit conversion (pure) — ADR-v2-056.

Find "<number> <unit> (in|to) <unit>" spans and replace them with the computed value, using a
built-in dependency-free factor table + temperature formulae. The full pint registry is deferred.
"""
from __future__ import annotations

import re

# unit → factor to the dimension's base unit.
_LEN = {"meter": 1.0, "meters": 1.0, "m": 1.0, "kilometer": 1000.0, "kilometers": 1000.0,
        "km": 1000.0, "centimeter": 0.01, "centimeters": 0.01, "cm": 0.01,
        "millimeter": 0.001, "millimeters": 0.001, "mm": 0.001, "mile": 1609.344,
        "miles": 1609.344, "foot": 0.3048, "feet": 0.3048, "ft": 0.3048, "inch": 0.0254,
        "inches": 0.0254, "yard": 0.9144, "yards": 0.9144}
_MASS = {"gram": 1.0, "grams": 1.0, "g": 1.0, "kilogram": 1000.0, "kilograms": 1000.0,
         "kg": 1000.0, "pound": 453.592, "pounds": 453.592, "lb": 453.592, "lbs": 453.592,
         "ounce": 28.3495, "ounces": 28.3495, "oz": 28.3495}
_VOL = {"liter": 1.0, "liters": 1.0, "l": 1.0, "milliliter": 0.001, "milliliters": 0.001,
        "ml": 0.001, "cup": 0.236588, "cups": 0.236588, "gallon": 3.78541, "gallons": 3.78541,
        "pint": 0.473176, "pints": 0.473176, "quart": 0.946353, "quarts": 0.946353}
_DIMS = {"length": _LEN, "mass": _MASS, "volume": _VOL}
_UNIT_DIM = {u: dim for dim, tbl in _DIMS.items() for u in tbl}
_TEMP = frozenset(["celsius", "fahrenheit", "kelvin"])

_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}

_EXPR = re.compile(r"\b(\d+(?:\.\d+)?|[a-z]+)\s+([a-z]+)\s+(?:in|to)\s+([a-z]+)\b", re.IGNORECASE)


def _value(tok: str):
    t = tok.lower()
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        return float(t)
    return _NUM_WORDS.get(t)


def _temp(val: float, u1: str, u2: str) -> float:
    c = val if u1 == "celsius" else (val - 32) / 1.8 if u1 == "fahrenheit" else val - 273.15
    if u2 == "celsius":
        return c
    if u2 == "fahrenheit":
        return c * 1.8 + 32
    return c + 273.15


def _convert(val: float, u1: str, u2: str):
    if u1 in _TEMP and u2 in _TEMP:
        return _temp(val, u1, u2)
    d1, d2 = _UNIT_DIM.get(u1), _UNIT_DIM.get(u2)
    if d1 and d1 == d2:
        return val * _DIMS[d1][u1] / _DIMS[d1][u2]
    return None


def _fmt(x: float) -> str:
    r = round(x, 2)
    return str(int(r)) if r == int(r) else f"{r:g}"


def apply_conversions(text: str) -> str:
    """Replace spoken unit conversions in ``text`` with the computed value. Pure."""
    if not text:
        return text

    def repl(m: re.Match) -> str:
        val = _value(m.group(1))
        if val is None:
            return m.group(0)
        result = _convert(val, m.group(2).lower(), m.group(3).lower())
        if result is None:
            return m.group(0)
        return f"{_fmt(result)} {m.group(3)}"

    return _EXPR.sub(repl, text)
