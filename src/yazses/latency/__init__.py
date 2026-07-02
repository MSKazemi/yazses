"""Adaptive Latency Governor (ADR-v2-073).

Adapt the decode policy to machine load; use a distil draft for speculative decoding when idle.
The ``governor`` module is the pure policy selector; the psutil read, draft model, and
speculative-decode loop are deferred behind a ``latency`` extra. OFF by default.
"""
