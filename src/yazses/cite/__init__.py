"""Citation-by-Voice from a local BibTeX/CSL library (ADR-v2-071).

"cite Vaswani 2017" → a formatted citation, fully offline. The ``library`` module is the pure
BibTeX parser + fuzzy resolver + formatter; an embedding index for large libraries is deferred.
OFF by default.
"""
