"""Vocal-Strain Guard (ADR-v2-034).

An ergonomic guardrail for heavy voice users: detect rising vocal fatigue (jitter, shimmer,
HNR drift) over a session and suggest a break. The ``strain`` module is the pure scoring +
trend decision; biomarkers come from the existing parselmouth dep. Advisory only, never
diagnostic. OFF by default.
"""
