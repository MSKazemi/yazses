"""Predictive dictation completion (ADR-v2-016).

A tiny on-device LLM proposes the rest of a phrase on a pause; you accept by voice.
This package's ``complete`` module is the pure control layer (parse accept/decline,
merge an accepted suggestion); the generator (llama.cpp, reused from ADR-013) is
lazy behind the ``predict`` extra and runs in a background thread so it never blocks
injection. OFF by default.
"""
