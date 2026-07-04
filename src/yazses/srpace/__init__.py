"""SRPace — screen-reader-paced injection (ADR-v2-120).

Pace injected text to a screen reader's reading rate, clause-chunked, instead of one burst — so a
blind user's screen reader can keep up and announce coherently. The ``schedule`` module is the
pure chunker + timing planner; the injector consumes the schedule. OFF by default.
"""
