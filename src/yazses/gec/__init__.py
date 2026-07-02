"""Grammar Repair — minimal-edit GEC (ADR-v2-050).

Fix article/agreement errors in L2 dictation with minimal edits, register-preserving. The
``guard`` module is the pure safety primitive (``is_minimal_edit``) + a dependency-free article
rule tier; the CoEdIT minimal-edit LM is lazy behind a ``gec`` extra, always gated by the guard.
OFF by default.
"""
