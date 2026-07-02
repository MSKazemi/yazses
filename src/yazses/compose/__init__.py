"""Compose-in-Target-Language (ADR-v2-049).

Dictate in your strongest language and inject text in a target language. The ``route`` module
is the pure routing + plausibility-guard core (inverse of Wave D's X→English translation); the
MADLAD/SeamlessM4T MT model is lazy behind the ``translate`` extra. OFF by default.
"""
