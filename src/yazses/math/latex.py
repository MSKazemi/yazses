"""Spoken-math → LaTeX grammar (pure) — ADR-v2-032.

Handles the common spoken-math vocabulary (greek, operators, functions/symbols) and a few
templates (squared/cubed, square root of, to the). Intentionally limited — arbitrary nested
expressions route to a deferred MathSpeech model. Pure and deterministic.
"""
from __future__ import annotations

import re

# Templates run before word substitution; each captures a single following token.
_TOKEN = r"([A-Za-z0-9]+)"

# Single-word spoken → LaTeX vocabulary.
_WORDS = {
    "alpha": r"\alpha", "beta": r"\beta", "gamma": r"\gamma", "delta": r"\delta",
    "epsilon": r"\epsilon", "theta": r"\theta", "lambda": r"\lambda", "mu": r"\mu",
    "pi": r"\pi", "sigma": r"\sigma", "phi": r"\phi", "omega": r"\omega",
    "infinity": r"\infty", "integral": r"\int", "sum": r"\sum", "product": r"\prod",
    "times": r"\times", "divided by": r"\div", "plus": "+", "minus": "-",
    "equals": "=", "partial": r"\partial", "nabla": r"\nabla",
}


def spoken_to_latex(text: str) -> str:
    """Convert common spoken math to LaTeX. Pure.

    Applies templates (``x squared`` → ``x^{2}``, ``square root of x`` → ``\\sqrt{x}``,
    ``a to the b`` → ``a^{b}``) then substitutes the vocabulary. Falls back to leaving
    unknown words untouched. Intentionally limited to the common cases.
    """
    s = f" {(text or '').strip()} "
    s = re.sub(rf"\bsquare root of {_TOKEN}", r"\\sqrt{\1}", s, flags=re.IGNORECASE)
    s = re.sub(rf"{_TOKEN} squared\b", r"\1^{2}", s, flags=re.IGNORECASE)
    s = re.sub(rf"{_TOKEN} cubed\b", r"\1^{3}", s, flags=re.IGNORECASE)
    s = re.sub(rf"{_TOKEN} to the {_TOKEN}\b", r"\1^{\2}", s, flags=re.IGNORECASE)
    # multi-word vocab first (e.g. "divided by") then single words
    for phrase, latex in sorted(_WORDS.items(), key=lambda kv: -len(kv[0])):
        s = re.sub(rf"\b{re.escape(phrase)}\b", latex.replace("\\", "\\\\"), s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()
