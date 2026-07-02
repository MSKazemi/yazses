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

    expr = re.sub(r"[^0-9+\-*/().% ]", "", t).strip()
    if not re.search(r"\d", expr) or not re.search(r"[-+*/]", expr):
        return None
    try:
        value = _safe_eval(ast.parse(expr, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
        return None
    return _format(value)
