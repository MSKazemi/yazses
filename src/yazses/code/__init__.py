"""Spoken Code Mode — syntax-aware programming by voice (ADR-v2-031).

Spoken symbols → punctuation and word-groups → cased identifiers, so you can dictate code.
The ``spoken`` module is the pure grammar (symbol substitution + identifier casing); LSP
completion via the existing NeovimBridge is a deferred enhancement. OFF by default.
"""
