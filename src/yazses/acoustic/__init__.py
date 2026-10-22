"""Acoustic Context Profiles (ADR-v2-039, amended 2026-10-15).

A pure quiet/noisy classifier computed from the quietest frames of the hold-to-talk burst itself,
and a floor-relative, clamped adjustment of the silence gate. ``profiles`` is the scene->policy
map plus hysteresis, ``scene`` the pure classifier, ``gate`` the numpy half the daemon calls.
In-memory only, never written to config.toml. OFF by default.
"""
