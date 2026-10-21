"""Vocal-Strain Guard (ADR-v2-034).

An ergonomic guardrail for heavy voice users: detect rising vocal fatigue (jitter, shimmer,
HNR drift) over a session and suggest a break. The ``strain`` module is the pure scoring +
trend decision; ``biomarkers`` measures jitter/shimmer/HNR through parselmouth (the optional
``prosody`` extra, imported lazily) and keeps the pure session history that feeds it. Not
yet called by the daemon. Advisory only, never diagnostic. OFF by default.
"""
