"""Mouth-Sound Switch Access (ADR-v2-097).

Non-verbal mouth sounds drive single-switch scanning, the switch-access method of AAC. ``scan``
is the pure classifier (and the original two-switch cursor); ``detect`` is the numpy-only onset
detector + feature extractor that feeds it from an idle audio stream; ``scanner`` is the pure,
clock-injected single-switch scan (items, highlight timing, select-at-onset); ``runtime`` is the
daemon's thin shell (microphone, worker, pointer sink, command runner). OFF by default.
"""
