"""Vocal-Strain Guard (ADR-v2-034).

An ergonomic guardrail for heavy voice users: detect rising vocal fatigue (jitter, shimmer,
HNR drift) over a session and suggest a break. The ``strain`` module is the pure scoring +
trend decision; ``biomarkers`` measures jitter/shimmer/HNR through parselmouth (the optional
``prosody`` extra, imported lazily) and keeps the pure session history that feeds it;
``runtime`` is the daemon glue — a worker thread measures each decoded burst off the hot
path and raises one advisory notification when the history says so. Advisory only, never
diagnostic. Thresholds tuned on synthetic signals only. OFF by default.
"""
