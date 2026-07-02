"""Two-Way Live Interpreter (ADR-v2-044).

Face-to-face interpreting: two speakers alternate, each turn is detected and translated into
the other language. The ``turns`` module is the pure pair-parsing/turn-routing core; the S2S/
translation model reuses the Whisper translate path + TTS, lazy-loaded. OFF by default.
"""
