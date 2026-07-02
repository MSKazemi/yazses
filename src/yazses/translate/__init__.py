"""Real-time offline speech translation (ADR-v2-014).

Dictate in one language, inject another. X→English reuses Whisper's built-in
``task=translate`` (zero new deps); other targets need the Seamless backend (opt-in,
behind the ``translate`` extra). This package's ``mode`` module is the pure decision
layer; the STT call carries the chosen task. OFF by default.
"""
