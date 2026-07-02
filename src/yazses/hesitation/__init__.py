"""Hesitation-Hold Endpointing (ADR-v2-101).

Hold the turn open on a *filled* hesitation ("uhh…") instead of cutting the speaker off. The
``endpoint`` module is the pure filled-pause detector + endpoint rule; F0/spectral extraction is the
lazy extra. OFF by default.
"""
