"""Safe inline arithmetic evaluation (pure) — ADR-v2-086.

Map spoken math to an expression and evaluate it through a restricted AST walker (never Python
``eval``). Pure and deterministic; algebra and date math are deferred.
"""
from __future__ import annotations

import ast
import operator
import re

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos, ast.Mod: operator.mod,
}
_WORDS = [
    ("multiplied by", "*"), ("divided by", "/"), ("plus", "+"), ("minus", "-"),
    ("times", "*"), ("over", "/"),
]


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("non-numeric constant")
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("disallowed expression")


def _format(value) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{round(value, 6):g}"
    return str(value)


def _is_a_hyphenated_token(expr: str) -> bool:
    """True when the only operator is a hyphen with nothing spaced around it. Pure.

    The letters guard in `evaluate` stops prose, but a string of digits and hyphens has
    no letters in it, and a hyphen between two numbers is far more often a range, a
    score, a phone number or a span of years than a subtraction. Measured on a real
    corpus this fired once in 1422 bursts -- on `2-2`, which is at least as likely to be
    a score as arithmetic -- and the same rule admitted:

        10-15      ->  -5        a range
        2024-2025  ->  -1        a span of years
        9-11       ->  -2
        555-1234   ->  -679      a phone number
        3-1        ->  2         a score

    Each of those REPLACES the whole utterance, and `[compute] enabled` is seeded on for
    every new install, so this is the default experience rather than an opt-in risk.

    Dictated subtraction does not look like this. "seven minus three" becomes `7 - 3`
    because the word substitution leaves the spaces it found, and someone typing an
    expression writes `7 - 3` too. So a hyphen with whitespace on either side still
    computes; a bare `N-N` does not.

    Restricted to `-` on purpose: `+`, `*` and `/` do not appear in dates, scores, phone
    numbers or version strings, so `2+2*3` is left alone. And the rule only applies when
    the hyphen is the ONLY operator -- `2+2-3` is unambiguously arithmetic.

    A missed computation costs the user typing the answer; a false one silently replaces
    what they said with a wrong number, which they may never re-read.
    """
    if re.search(r"[+*/]", expr):
        return False
    return re.search(r"(?<=\d)-(?=\d)", expr) is not None and " - " not in expr


def evaluate(text: str):
    """Evaluate a spoken arithmetic/percentage expression to a string answer, or ``None``. Pure."""
    t = (text or "").lower()
    t = re.sub(r"\b(what'?s|what is|calculate|compute|equals?|the answer to|how much is)\b", " ", t)
    t = t.replace("percent", "%")
    # "15% of 240" → (15/100*240); bare "15%" → (15/100)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)", r"(\1/100*\2)", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", t)
    for word, sym in _WORDS:
        t = re.sub(rf"\b{re.escape(word)}\b", sym, t)

    # WHOLE-utterance, as the docstring says. Stripping every non-operator character
    # instead meant any sentence carrying two numbers and one operator word collapsed to
    # an expression, and the utterance was REPLACED by the answer:
    #
    #     "I ran 5 miles over 2 days"    ->  "2.5"
    #     "chapter 3 minus chapter 1"    ->  "2"
    #     "we met 2 times in 3 days"     ->  "6"
    #
    # Six of eight ordinary sentences. "over" and "times" are common English words, and
    # this transform does not mangle the text -- it discards it. So anything left over
    # after the lead-in words and the operator words have been consumed means this was
    # prose, and prose is returned untouched.
    if re.search(r"[a-z]", t):
        return None
    expr = re.sub(r"[^0-9+\-*/().% ]", "", t).strip()
    if not re.search(r"\d", expr) or not re.search(r"[-+*/]", expr):
        return None
    if _is_a_hyphenated_token(expr):
        return None
    try:
        value = _safe_eval(ast.parse(expr, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
        return None
    return _format(value)
