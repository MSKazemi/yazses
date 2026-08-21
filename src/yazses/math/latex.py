"""Spoken-math → LaTeX grammar (pure) — ADR-v2-032.

Handles the common spoken-math vocabulary (greek, operators, functions/symbols) and a few
templates (squared/cubed, square root of, to the). Intentionally limited — arbitrary nested
expressions route to a deferred MathSpeech model. Pure and deterministic.

.. warning::

   **Not safe to wire onto the dictation path as it stands.** The rules match their
   keywords anywhere in an utterance, and those keywords are ordinary English, so plain
   prose is rewritten:

       "she squared her shoulders and left"  ->  "she^{2} her shoulders and left"
       "plus I think we should go"           ->  "+ I think we should go"

   Harmless today — the feature is unwired and `spoken_to_latex` is called from nothing
   outside this package — which is exactly why it is written down here rather than left
   to be discovered by whoever wires it. Anything routing dictation through this needs a
   way to know the utterance is *maths* first (a mode, a command key, an explicit
   trigger); a broader keyword list makes it worse, not better.

   Found by feeding realistic prose through the function — the same five-minute check
   that turned up real corruption in `itn/normalize.py`, `acronyms/glossary.py` and
   `selfrepair/repair.py`, all of which *were* reachable.
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
