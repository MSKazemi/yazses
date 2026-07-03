"""Lexicon-driven diacritics restoration (pure) — ADR-v2-122.

Restore diacritics on whole words via an unambiguous built-in lexicon (extendable per user),
preserving capitalization. Words that are also plain-English words ("resume", "expose") are
deliberately absent — those need context and stay with the optional neural backend.
"""
from __future__ import annotations

import re

_LEXICON = {
    "cafe": "café", "naive": "naïve", "naivete": "naïveté", "jalapeno": "jalapeño",
    "senor": "señor", "senora": "señora", "senorita": "señorita", "cliche": "cliché",
    "fiance": "fiancé", "fiancee": "fiancée", "creme": "crème", "entree": "entrée",
    "souffle": "soufflé", "saute": "sauté", "sauteed": "sautéed", "touche": "touché",
    "crepe": "crêpe", "facade": "façade", "garcon": "garçon", "protege": "protégé",
    "protegee": "protégée", "voila": "voilà", "pinata": "piñata", "manana": "mañana",
    "doppelganger": "doppelgänger", "smorgasbord": "smörgåsbord", "jager": "jäger",
    "deja": "déjà", "tete-a-tete": "tête-à-tête", "raison d'etre": "raison d'être",
    "creme brulee": "crème brûlée", "piece de resistance": "pièce de résistance",
}


def _match_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def restore_diacritics(text: str, extra: dict[str, str] | None = None) -> str:
    """Restore diacritics on known words/phrases in ``text``, preserving case. Pure.

    ``extra`` merges user mappings over the built-in lexicon (user wins).
    """
    lexicon = {**_LEXICON, **(extra or {})}
    s = text or ""
    phrases = sorted((k for k in lexicon if not k.isalpha()), key=len, reverse=True)
    for phrase in phrases:
        s = re.sub(re.escape(phrase), lambda m: _match_case(m.group(), lexicon[phrase]),
                   s, flags=re.IGNORECASE)

    def _word(m: re.Match) -> str:
        hit = lexicon.get(m.group().lower())
        return _match_case(m.group(), hit) if hit else m.group()

    return re.sub(r"[A-Za-z]+", _word, s)
