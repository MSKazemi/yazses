"""Whisper-Aware Mode (ADR-v2-100).

Detect whispered phonation (no voicing, flat spectral tilt) and adapt gain/VAD/prompt. The
``detect`` module is the pure DSP detector + adaptation map (pure numpy). OFF by default.
"""
