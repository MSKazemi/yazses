"""Inline Compute (ADR-v2-086).

Evaluate spoken arithmetic/percentages and inject the answer. The ``evaluate`` module is the pure
safe-AST evaluator; sympy algebra and dateutil date math are deferred behind a ``compute`` extra.
OFF by default.
"""
