"""Hesitation-Hold Endpointing (ADR-v2-101).

Hold the turn open on a *filled* hesitation ("uhh…") instead of cutting the speaker off. The
``endpoint`` module is the pure filled-pause detector + endpoint rule; ``stream`` feeds it from the
numpy F0/spectral-flux tracker in ``yazses.audio.pitch`` (no optional extra); ``handsfree`` builds
the monitor that extends an ``[autostop]`` turn's silence timeout. Experimental; OFF by default.
"""
