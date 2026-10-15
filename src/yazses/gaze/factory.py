"""Gaze backend factory (dormancy + graceful degradation).

``None`` when ``[gaze] enabled = false`` or when the chosen backend cannot run —
callers treat ``None`` as "no gaze" and skip targeting, so the daemon never crashes
and the camera is never opened unless explicitly enabled (ADR-011).

Degrading silently is the reason the message matters. Gaze targeting that never runs
has no other symptom: `yazses features` still shows the capability ON, nothing is
typed differently, and the only account of what happened is one `log.warning`. It used
to be a single blanket "install the ``gaze`` extra", which is wrong twice over.

* ``backend = "l2cs"`` is never fixed by that extra. ``pyproject.toml`` declares
  ``gaze`` as mediapipe only, deliberately: l2cs pulls an older torch that conflicts
  with a unified resolution, so it is left to a manual ``pip install "l2cs>=2.0"``.
  Naming the extra sends the user after a package that cannot supply the backend they
  selected -- the same lie ``system/backends.py`` was written to stop telling for
  ``resemblyzer`` and ``pyannote``.
* ``MediapipeGazeBackend`` fetches a ~3.7 MB FaceLandmarker model from Google on first
  use. On a firewalled machine that raises, and the user -- extra already installed --
  was told to install it again.

So the three answers are kept apart: the adapter was never shipped, a dependency is
missing (and the remedy names only what can actually provide it), or everything is
installed and the backend still would not start.
"""
from __future__ import annotations

import logging

from yazses.gaze.base import GazeBackend
from yazses.system.backends import probe_backend

log = logging.getLogger(__name__)

#: Adapter module and third-party import name per backend. ``extra`` is the pip extra
#: that provides the dependency, or ``None`` where no extra does -- l2cs is excluded
#: from the ``gaze`` extra on purpose (see the module docstring), so it must never be
#: advised one.
_BACKENDS: dict[str, tuple[str, str, str | None]] = {
    "mediapipe": ("yazses.gaze.mediapipe_backend", "mediapipe", "gaze"),
    "l2cs": ("yazses.gaze.l2cs", "l2cs", None),
}


def gaze_backend_available(config) -> tuple[bool, str]:
    """``(available, why_not)`` for the chosen backend, **without constructing it**.

    `yazses gaze status` used to answer "are the gaze dependencies present?" by calling
    :func:`build_gaze` and closing the result. Building the MediaPipe backend loads the
    landmarker and, on a machine that does not have it cached, *downloads the ~3.7 MB model
    from the network* -- so a read-only status command could reach out, and took seconds. This
    asks the same dependency question (:func:`probe_backend` is what ``build_gaze`` asks first)
    and stops there: no model, no camera, no socket. What it cannot say is whether a model
    download would succeed, which is the one thing a status command should not try.
    """
    backend = str(getattr(config, "backend", "mediapipe") or "mediapipe")
    spec = _BACKENDS.get(backend)
    if spec is None:
        return False, f"unknown gaze backend {backend!r} (expected mediapipe or l2cs)"
    adapter, requires, extra = spec
    status = probe_backend(backend, adapter=adapter, requires=(requires,), extra=extra)
    return (True, "") if status.available else (False, status.message)


def build_gaze(config, perception=None) -> GazeBackend | None:
    """Return a gaze backend for *config*, or None when dormant/unavailable.

    *perception* is the daemon's shared camera source (ADR-v2-145), passed only when
    :func:`yazses.gaze.shared.shared_source_for_gaze` said gaze may use it. With it
    the MediaPipe backend is a lease on that source instead of a camera of its own;
    without it (every caller but the daemon, and every install with ``[perception]``
    off) this returns exactly what it always did. The dependency probe above runs
    either way, so a missing extra is still named by the same message.
    """
    if not getattr(config, "enabled", False):
        return None

    backend = str(getattr(config, "backend", "mediapipe") or "mediapipe")
    spec = _BACKENDS.get(backend)
    if spec is None:
        # `none` is a documented value meaning "off"; anything else is a typo, and
        # neither has anything to install.
        if backend != "none":
            log.warning(
                "Gaze backend %r is unknown (expected %s); look-to-pane stays dormant.",
                backend, " or ".join(sorted(_BACKENDS)),
            )
        return None

    adapter, requires, extra = spec
    status = probe_backend(backend, adapter=adapter, requires=(requires,), extra=extra)
    if not status.available:
        log.warning(
            "Gaze is enabled but %s. Look-to-pane stays dormant.", status.message
        )
        return None

    try:
        if backend == "mediapipe":
            if perception is not None:
                from yazses.gaze.shared import SharedGazeBackend

                return SharedGazeBackend(
                    perception.consumer("gaze"),
                    failure_reason=lambda: perception.status().failure_reason,
                )
            from yazses.gaze.mediapipe_backend import MediapipeGazeBackend

            return MediapipeGazeBackend(config)
        from yazses.gaze.l2cs import L2csGazeBackend

        return L2csGazeBackend(config)
    except Exception as exc:
        # The dependency is installed, so no extra is the answer. What is left is the
        # model download (fetched on first use) or the camera, and the error names it.
        log.warning(
            "Gaze is enabled and the %r backend is installed, but it could not "
            "start: %s. The FaceLandmarker model is downloaded on first use, so a "
            "blocked or interrupted download is the usual cause. Look-to-pane stays "
            "dormant.",
            backend, exc,
        )
        return None
