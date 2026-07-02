"""Confidence-Gated Re-Ask (ADR-v2-077) — Wave J flagship.

Hold a low-confidence span and interactively resolve it instead of injecting a guess. The
``confidence`` module is the pure span finder + confusion sets + choice parser; a learned
confidence-estimator head is deferred. OFF by default.
"""
