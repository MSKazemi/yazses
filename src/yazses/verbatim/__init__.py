"""Verbatim ⇄ Autoformat Live Toggle (ADR-v2-078).

Two reserved phrases flip a per-burst flag that freezes/restores all ITN + voice-punctuation +
reflow, mid-burst. The ``gate`` module is the pure command detector + mode state. OFF by default.
"""
