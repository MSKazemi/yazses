"""Gaze backend factory (dormancy + graceful degradation).

``None`` when ``[gaze] enabled = false`` or when the optional ``gaze`` extra
(l2cs-net / opencv / mediapipe) is unavailable — callers treat ``None`` as "no
gaze" and skip targeting, so the daemon never crashes and the camera is never
opened unless explicitly enabled (ADR-011).
"""
from __future__ import annotations

import logging

from yazses.gaze.base import GazeBackend

log = logging.getLogger(__name__)


def build_gaze(config) -> GazeBackend | None:
    """Return a gaze backend for *config*, or None when dormant/unavailable."""
    if not getattr(config, "enabled", False):
        return None
    backend = getattr(config, "backend", "mediapipe")
    try:
        if backend == "mediapipe":
            from yazses.gaze.mediapipe_backend import MediapipeGazeBackend

            return MediapipeGazeBackend(config)
        if backend == "l2cs":
            from yazses.gaze.l2cs import L2csGazeBackend

            return L2csGazeBackend(config)
        log.warning("Unknown gaze backend %r; gaze disabled.", backend)
        return None
    except Exception as exc:
        log.warning(
            "Gaze backend %r unavailable (%s); install the `gaze` extra. "
            "Look-to-pane stays dormant.",
            backend, exc,
        )
        return None
