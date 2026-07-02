"""Voice Fuzzy File Open (ADR-v2-080).

"open the notes about the mortgage" → fuzzy-match a local file index and launch it. The ``match``
module is the pure ranker; the EmbeddingGemma semantic tier is deferred behind a ``semanticfs``
extra. OFF by default.
"""
