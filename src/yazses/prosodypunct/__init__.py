"""Prosodic Auto-Punctuation — acoustic, word-free sentence structure (ADR-v2-104).

Insert '. , ?' from prosody alone (pause, pitch reset, terminal rise), no spoken punctuation words.
The ``punctuate`` module is the pure decision engine; F0/energy extraction is the lazy extra. OFF by
default.
"""
