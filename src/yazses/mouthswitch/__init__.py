"""Mouth-Sound Switch Access (ADR-v2-097).

Non-verbal mouth sounds (pop/click/sh) drive a timed scan-and-select selector, the switch-scanning
AAC access method. The ``scan`` module is the pure classifier + scan cursor; ``detect`` is the
numpy-only onset detector + feature extractor that feeds it from an idle audio stream. OFF by
default.
"""
